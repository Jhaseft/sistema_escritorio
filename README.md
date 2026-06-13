# AttendanceBridge — Puente de Asistencia Dahua → Web

Captura **en tiempo real** los fichajes (huella / tarjeta / rostro) del terminal de
control de acceso Dahua, los guarda en una base local y cada noche genera un Excel
y lo envía a tu sistema web. Funciona **sin abrir Smart PSS**, en segundo plano.

---

## 📁 Contenido de la carpeta `D:\AttendanceBridge\`

| Archivo | Para qué sirve |
|---------|----------------|
| `capture_service.py` | Servicio 24/7: escucha el terminal y guarda cada fichaje |
| `export_nightly.py`  | Corre a las 23:00: genera Excel y lo manda a la web |
| `config.json`        | **Configuración** (IP del equipo, datos de tu web, horario) |
| `attendance.db`      | Base de datos local con los fichajes (se crea sola) |
| `sdk\`               | DLLs del NetSDK de Dahua (incluidos = portable) |
| `exports\`           | Excels generados cada noche |
| `logs\`              | Registros de actividad (`capture.log`, `export.log`) |
| `install.bat`        | **Instala** (registra el arranque automático y el envío diario) |
| `uninstall.bat`      | Desinstala las tareas |
| `status.bat`         | Muestra si está corriendo y los últimos fichajes |

---

## ⚙️ Cómo funciona en segundo plano

Se instala como **dos Tareas Programadas de Windows** (cuenta `SYSTEM`, sin ventana):

1. **AttendanceBridge-Capture** → arranca **al encender el PC** y queda escuchando
   siempre. Si el equipo se desconecta, **se reconecta solo**. Si el proceso falla,
   Windows lo **reinicia** automáticamente.
2. **AttendanceBridge-Export** → se dispara **todos los días a las 23:00**: arma el
   Excel del día y lo envía a tu web.

No necesita que Smart PSS esté abierto ni que haya una sesión de Windows iniciada.

---

## 🚀 Instalación (en este PC)

1. Edita `config.json` con los datos de tu **sistema web** (ver abajo).
2. Doble clic en **`install.bat`** → acepta el aviso de Administrador.
3. Listo. Verifica con **`status.bat`**.

---

## 🌐 Configurar el envío web (`config.json` → `web`)

```json
"web": {
  "url": "https://tusistema.com/api/asistencia",
  "method": "POST",
  "format": "excel_multipart",   // "excel_multipart" sube el .xlsx  |  "json" manda filas JSON
  "file_field": "file",          // nombre del campo del archivo (solo excel_multipart)
  "auth_header": "Authorization",
  "auth_value": "Bearer TU_TOKEN",
  "extra_fields": {}             // campos extra opcionales (ej. {"sucursal":"1"})
}
```

- `export.scope`: `"today"` (solo fichajes del día) o `"unsent"` (todo lo no enviado).
- `export.run_time`: hora del envío, formato `"23:00"`.

> Mientras la URL/token sigan con valores de ejemplo, el exportador **genera el Excel
> pero no lo envía** (lo verás en `logs\export.log`).

---

## 🖥️ Instalar en OTRA máquina

La carpeta es **portable** (los DLLs del SDK van incluidos en `sdk\`). En la otra PC:

1. Instala **Python 3 (64-bit)** desde python.org y marca **"Add Python to PATH"**.
2. Copia toda la carpeta `AttendanceBridge` a la otra PC (ej. a `D:\AttendanceBridge`).
   - Si la ruta cambia, ajusta en `config.json`: `sdk_dir`, `db_path` y `export.excel_dir`.
3. En `config.json`, pon la **IP / usuario / contraseña** del terminal de esa PC.
4. Doble clic en **`install.bat`** (como Administrador).

Requisitos en la otra máquina: Windows 64-bit, Python 3 64-bit, y **estar en la misma
red** que el terminal Dahua (puerto 37777 alcanzable).

---

## 🔎 Verificar / mantener

- **¿Está corriendo?** → `status.bat`, o Programador de tareas → busca `AttendanceBridge-*`.
- **Logs** → `logs\capture.log` (fichajes en vivo), `logs\export.log` (envíos).
- **Probar el envío ahora** (sin esperar a las 23:00):
  `python export_nightly.py`
- **Desinstalar** → `uninstall.bat`.

---

## ⚠️ Notas

- La captura es **desde que se instala en adelante** (no recupera el histórico viejo,
  que queda en la base cifrada de Smart PSS).
- El PC debe estar **encendido** para capturar; si se apaga, se pierden los fichajes
  de ese rato (el terminal no garantiza reenvío de eventos offline).
- Solo una instancia del capturador debe correr a la vez (el equipo limita conexiones).
