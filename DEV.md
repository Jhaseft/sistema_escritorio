# AttendanceBridge — Guía de desarrollador

Documentación técnica del puente Dahua → Laravel. Cubre cómo se captura la
información, qué se envía, cómo operar el servicio (reiniciar, logs, instalar,
desinstalar) y los puntos de fallo.

---

## 1. Arquitectura en una imagen

```
 Terminal Dahua (192.168.0.118:37777)
        │  eventos de control de acceso en tiempo real (protocolo binario)
        ▼
 dhnetsdk.dll  (NetSDK, cargado vía ctypes)
        │  llama al callback on_message()
        ▼
 capture_service.py
   ├─ on_message()  → parsea el struct → db_insert() → attendance.db (sent=0)
   │                                          └─ encola id en SEND_Q
   ├─ sender_worker() → POST JSON → Laravel /api/attendance → si 2xx: sent=1
   └─ retry_worker()  → cada 60s reencola los sent=0 (web caída, etc.)
        │
        ▼
 Laravel (D:\Horario_Oktava)  POST /api/attendance  (Bearer token)
        └─ AttendanceBridgeController → AttendanceLog::updateOrCreate → MySQL
```

Dos procesos clave conviven dentro de **un solo proceso Python** (hilos):
- El callback del SDK (corre en un hilo del SDK).
- `sender_worker` y `retry_worker` (hilos daemon que arranca `main()`).

---

## 2. Cómo se "agarra" la información

No se consulta ninguna base del Dahua. El terminal **empuja** cada fichaje por
la red y el SDK nos lo entrega. Secuencia exacta:

1. **Carga del SDK** (`capture_service.py`, sección *load SDK*): `os.add_dll_directory`
   + `ctypes.CDLL("dhnetsdk.dll")`. Se declaran `restype`/`argtypes` de las
   funciones que usamos.
2. **Registro de callbacks** en `main()`:
   - `CLIENT_Init(DISC_CB)` → callback de desconexión.
   - `CLIENT_SetAutoReconnect(RECON_CB)` → reconexión automática.
   - `CLIENT_SetDVRMessCallBack(MSG_CB)` → **el importante**: recibe los eventos.
3. **Login**: `CLIENT_LoginWithHighLevelSecurity(LIN, LOUT)` con IP/puerto/user/pass
   de `config.json`. Devuelve un *handle* (`h`). Si falla, reintenta cada 10s.
4. **Suscripción**: `CLIENT_StartListenEx(h)` → a partir de aquí, cada fichaje
   dispara `on_message`.
5. **`on_message(lCommand, ...)`** (el corazón):
   - Filtra `lCommand == NET_ALARM_ACCESS_CTL_EVENT` (`0x3181`).
   - `cast(pStuEvent, POINTER(ALARM_ACCESS_CTL)).contents` → interpreta el puntero
     crudo como la estructura C `ALARM_ACCESS_CTL`.
   - Lee campos: `szUserID`, `szCardNo`, `emOpenMethod`, `bStatus`, `nDoor`,
     `emEventType`, `emAttendanceState`, `stuTime`.
   - Traduce códigos a texto con los diccionarios `METHOD`, `EVT`, `ATT`.
   - Arma la tupla `rec` y llama `db_insert()`.

> ⚠️ **Lo más frágil**: la clase `ALARM_ACCESS_CTL`. Es un *mapeo binario byte a
> byte* del struct C del SDK. Si el orden/tamaño/tipo de un campo no coincide con
> la versión del NetSDK, **todo lo que leas estará corrido** (basura). No la toques
> sin el header oficial `dhnetsdk.h`.

### La tabla local (buffer)
`attendance.db` → tabla `events`. Campo clave:
`UNIQUE(event_time, user_id, card_no, door, method)` + `INSERT OR IGNORE` =
**no se duplican** fichajes. `sent` (0/1) marca si ya llegó a la web.

---

## 3. Qué se envía y cómo

### El payload (JSON que recibe Laravel)
`sender_worker` toma un `id`, lo lee con `fetch_event()` y manda estas columnas
(`SEND_COLS`):

```json
{
  "id": 19, "event_time": "2026-06-13 11:04:42", "event_date": "2026-06-13",
  "user_id": "22", "card_no": "", "method": 7, "method_name": "Huella",
  "status": 1, "door": 1, "direction": 1, "direction_name": "Entrada",
  "attendance_state": 1, "attendance_name": "Entrada",
  "device_ip": "192.168.0.118", "captured_at": "2026-06-13 11:04:42"
}
```

### El mecanismo de envío (con garantía de entrega)
- **Cola** (`SEND_Q`): `on_message` encola el `id` recién insertado. No bloquea el
  callback del SDK (importante: si bloqueas el callback, pierdes eventos).
- **`sender_worker`**: saca ids de la cola, hace `post_event()`. Si la web responde
  **2xx → `mark_sent` (sent=1)**. Si no, lo deja `sent=0` y loguea.
- **`retry_worker`**: cada 60s busca `sent=0` y los reencola. Así, si tu web está
  caída o reinicia, los fichajes **no se pierden**: se reintentan hasta entrar.
- **Token**: `post_event` agrega `Authorization: Bearer <auth_value>` solo si
  `rt_auth_ready()` (hay token real). Laravel lo valida contra `BRIDGE_TOKEN`.

### Idempotencia de punta a punta
- Local: `UNIQUE(...)` evita reinsertar.
- Remoto: `AttendanceLog::updateOrCreate` con `unique(device_user_id, punched_at)`
  → si un reintento manda dos veces, **no duplica** en MySQL.

### Config relevante (`config.json` → `realtime`)
```json
"realtime": {
  "enabled": true,
  "url": "http://localhost:8000/api/attendance",
  "auth_header": "Authorization",
  "auth_value": "Bearer loquesea",
  "timeout": 10
}
```
- `enabled:false` o URL con `TU-SISTEMA-WEB` → `rt_is_configured()` da false → NO envía
  (solo guarda local). Lo verás en el log como "Envio en tiempo real DESACTIVADO".

---

## 4. Operación diaria (comandos)

> El servicio corre como `pythonw.exe capture_service.py` (oculto, sin ventana).

### Ver si está corriendo
```powershell
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
  Where-Object { $_.CommandLine -like "*capture_service.py*" } |
  Select-Object ProcessId, CreationDate
```
o simplemente: `status.bat`

### Ver logs en tiempo real
```powershell
Get-Content "D:\AttendanceBridge\logs\capture.log" -Wait -Tail 20
```
(`Ctrl+C` para salir). El archivo: `logs\capture.log`.

### Reiniciar (tras cambiar código o config) — el flujo correcto
```powershell
# 1) matar la instancia actual
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
  Where-Object { $_.CommandLine -like "*capture_service.py*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

# 2) volver a lanzar (oculto)
$pythonw = Join-Path (Split-Path (Get-Command python).Source) "pythonw.exe"
Start-Process -FilePath $pythonw -ArgumentList '"D:\AttendanceBridge\capture_service.py"' `
  -WorkingDirectory "D:\AttendanceBridge" -WindowStyle Hidden
```
> **Importante**: el proceso lee `config.json` y el código SOLO al arrancar. Cualquier
> cambio en `.py` o `config.json` requiere reiniciar para que tenga efecto.

### Depurar en primer plano (ver errores en vivo)
Para desarrollar, córrelo con `python` (no `pythonw`) en una consola: verás los
`print` y cualquier traceback directo.
```powershell
python D:\AttendanceBridge\capture_service.py
```

### Probar el envío sin ir al terminal
```powershell
python D:\AttendanceBridge\test_send.py          # manda un fichaje de prueba
python D:\AttendanceBridge\test_send.py --real   # manda el último real de la BD
```

### Inspeccionar la base local
```powershell
python D:\AttendanceBridge\db_summary.py
```

---

## 5. Instalar / Desinstalar

### Hay dos métodos de autostart
| Método | Script | Arranca | Auto-reinicio si crashea | Permisos |
|--------|--------|---------|--------------------------|----------|
| **Usuario** (actual) | `instalar.bat` → `install_user.ps1` | al iniciar sesión | ❌ no | sin admin |
| **Sistema** (robusto) | `install.bat` → `install.ps1` | al encender el PC | ✅ sí (tarea SYSTEM) | admin |

- Método usuario: crea un acceso directo en
  `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\AttendanceBridge.lnk`.
- Método sistema: crea la Tarea Programada `AttendanceBridge-Capture` (cuenta SYSTEM,
  `-AtStartup`, `RestartCount 999`).

### Desinstalar (quitar autostart)
```powershell
# si usaste el método usuario:
Remove-Item "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\AttendanceBridge.lnk"

# si usaste el método sistema (como admin):
Unregister-ScheduledTask -TaskName "AttendanceBridge-Capture" -Confirm:$false

# y matar el proceso vivo:
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
  Where-Object { $_.CommandLine -like "*capture_service.py*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```
`uninstall.bat` hace la parte de la tarea + matar proceso.

### Instalar en OTRA PC (o reinstalar en la tuya)
1. Instala **Python 3 64-bit** (marca *Add to PATH*). El SDK es 64-bit → Python
   **debe** ser 64-bit.
2. Copia toda la carpeta `AttendanceBridge` (los DLLs en `sdk\` van incluidos = portable).
3. Ajusta `config.json`: `sdk_dir`, `db_path`, IP/usuario/clave del terminal, y la
   sección `realtime` (URL de tu Laravel + token).
4. `pip install requests` (o deja que el instalador lo haga).
5. Ejecuta `instalar.bat` (usuario) o `install.bat` (sistema, como admin).
6. Verifica con `status.bat` y el log.

Requisitos de red: la PC debe alcanzar el terminal Dahua en el **puerto 37777**.

---

## 6. Qué falla y en qué momento (troubleshooting)

| Síntoma en el log | Momento | Causa probable | Solución |
|-------------------|---------|----------------|----------|
| `login fallo err=0x80000007` | al arrancar | password incorrecta | corregir `device.password` |
| `login fallo err=0x8000006b` | al arrancar | usuario/clave o equipo no responde | revisar credenciales / red |
| `login fallo` (cuelga reintentando) | al arrancar | IP/puerto mal o equipo apagado/otra red | ping a la IP, abrir 37777 |
| no aparecen `FICHAJE` al fichar | en uso | no llegó a `StartListenEx`, o el evento no es `0x3181` | ver si dice "Escuchando..."; revisar tipo de evento |
| `FICHAJE` con datos basura/raros | en uso | el struct `ALARM_ACCESS_CTL` no coincide con tu NetSDK | alinear struct con el `.h` oficial |
| `DESCONECTADO del equipo` | en uso | se cayó la red/equipo | se reconecta solo (`RECONECTADO`) |
| `Envio ... DESACTIVADO` | al arrancar | `realtime` con placeholder o `enabled:false` | poner URL/token reales y reiniciar |
| `web NO 2xx id=N (HTTP 404)` | al enviar | ruta no existe en Laravel | crear/registrar `POST /api/attendance` |
| `web NO 2xx id=N (HTTP 401)` | al enviar | token no coincide | igualar `auth_value` ↔ `BRIDGE_TOKEN` |
| `web NO 2xx id=N (HTTP 500)` | al enviar | error en el backend (tabla/SQL) | ver log de Laravel; correr migraciones |
| `error enviando id=N ... Connection refused` | al enviar | Laravel apagado | levantar el backend; el retry reenvía |
| `DB insert error` | al capturar | BD bloqueada/permisos | revisar `db_path`, permisos de escritura |
| el proceso desaparece y no vuelve | tras crash | usaste método "usuario" (sin auto-reinicio) | reabrir sesión o usar método "sistema" |

### Errores típicos del NetSDK (`CLIENT_GetLastError`)
- `0x80000007` → contraseña incorrecta.
- `0x8000006b` → fallo de login (usuario/clave o límite de conexiones).
- Si nada conecta: confirma que **solo una** instancia corre (el equipo limita
  sesiones simultáneas).

### Reglas de oro al depurar
1. Cambiaste algo → **reinicia** el proceso (lee config/código solo al arrancar).
2. ¿Captura pero no envía? → mira `sent` en la BD y el log "ENVIADO/NO 2xx".
3. ¿Envía pero no aparece en MySQL? → es el backend (mira el log de Laravel).
4. Para ver tracebacks, corre con `python` (no `pythonw`) en consola.
</content>
