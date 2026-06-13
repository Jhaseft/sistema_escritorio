"""
Servicio de captura 24/7 de fichajes del terminal Dahua (vía NetSDK).
Se suscribe a los eventos de control de acceso en tiempo real y guarda
cada fichaje en una base SQLite propia (attendance.db).
Auto-reconecta si el equipo se cae. Pensado para correr siempre (autostart).
"""
import os, json, time, sqlite3, ctypes, datetime, threading, queue
import urllib.request, urllib.error
from ctypes import (c_int, c_uint, c_long, c_char, c_byte, c_void_p, c_longlong,
                    c_char_p, Structure, POINTER, byref, sizeof, cast, WINFUNCTYPE)

BASE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(BASE, "config.json"), encoding="utf-8"))
SDK_DIR = CFG["sdk_dir"]
DEV = CFG["device"]
DB_PATH = CFG["db_path"]
RT = CFG.get("realtime", {})
LOG_PATH = os.path.join(BASE, "logs", "capture.log")
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

NET_ALARM_ACCESS_CTL_EVENT = 0x3181
METHOD = {1:"Password",2:"Tarjeta",3:"Tarjeta+Pwd",4:"Pwd+Tarjeta",5:"Remoto",6:"Boton",
          7:"Huella",8:"Pwd+Tarjeta+Huella",16:"Rostro",18:"Rostro+ID",20:"Bluetooth",
          15:"QR",22:"UserID+Pwd",23:"Rostro+Pwd"}
ATT = {0:"",1:"Entrada",2:"Salida",3:"Salida y regreso"}
EVT = {0:"",1:"Entrada",2:"Salida"}

def log(msg):
    line = f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

# ---------------- SQLite ----------------
def db_init():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.execute("""CREATE TABLE IF NOT EXISTS events(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_time TEXT, event_date TEXT,
        user_id TEXT, card_no TEXT, card_name TEXT,
        method INTEGER, method_name TEXT,
        status INTEGER, door INTEGER,
        direction INTEGER, direction_name TEXT,
        attendance_state INTEGER, attendance_name TEXT,
        device_ip TEXT, captured_at TEXT,
        sent INTEGER DEFAULT 0,
        UNIQUE(event_time, user_id, card_no, door, method))""")
    con.commit()
    return con

DBLOCK = threading.Lock()
def db_insert(con, rec):
    """Inserta el fichaje. Devuelve el id si es nuevo, o None si era duplicado/error."""
    with DBLOCK:
        try:
            cur = con.execute("""INSERT OR IGNORE INTO events
                (event_time,event_date,user_id,card_no,card_name,method,method_name,
                 status,door,direction,direction_name,attendance_state,attendance_name,
                 device_ip,captured_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rec)
            con.commit()
            return cur.lastrowid if cur.rowcount else None
        except Exception as e:
            log(f"DB insert error: {e}")
            return None

# ---------------- Envio en tiempo real a la web ----------------
SEND_Q = queue.Queue()
SEND_COLS = ["id","event_time","event_date","user_id","card_no","method","method_name",
             "status","door","direction","direction_name","attendance_state",
             "attendance_name","device_ip","captured_at"]

def rt_is_configured():
    """Envia si hay URL valida. El token es opcional (ver rt_auth_ready)."""
    if not RT.get("enabled"):
        return False
    url = RT.get("url", "")
    if not url or "TU-SISTEMA-WEB" in url:
        return False
    return True

def rt_auth_ready():
    """True solo si hay un token real configurado (no el placeholder)."""
    a = RT.get("auth_value", "")
    return bool(a) and "PON-TU-TOKEN" not in a

def fetch_event(con, rid):
    with DBLOCK:
        row = con.execute(
            f"SELECT {','.join(SEND_COLS)} FROM events WHERE id=?", (rid,)).fetchone()
    return dict(zip(SEND_COLS, row)) if row else None

def mark_sent(con, rid):
    with DBLOCK:
        con.execute("UPDATE events SET sent=1 WHERE id=?", (rid,))
        con.commit()

def post_event(payload):
    """POST del fichaje como JSON usando urllib (sin dependencias externas).
    Devuelve (codigo_http, texto). Lanza URLError si no hay respuesta (web caida)."""
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if RT.get("auth_header") and rt_auth_ready():
        headers[RT["auth_header"]] = RT["auth_value"]
    req = urllib.request.Request(RT["url"], data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=RT.get("timeout", 10)) as resp:
            return resp.getcode(), resp.read(200).decode(errors="ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read(200).decode(errors="ignore")

def sender_worker():
    """Toma ids de la cola y los envia a la web; marca sent=1 si la web responde 2xx."""
    while True:
        rid = SEND_Q.get()
        try:
            payload = fetch_event(CON, rid)
            if not payload:
                continue
            code, text = post_event(payload)
            if 200 <= code < 300:
                mark_sent(CON, rid)
                log(f"-> ENVIADO a la web id={rid} (HTTP {code})")
            else:
                log(f"web NO 2xx id={rid} (HTTP {code}); quedara para reintento")
        except Exception as e:
            log(f"error enviando id={rid} a la web: {e} (quedara para reintento)")
        finally:
            SEND_Q.task_done()

def retry_worker():
    """Cada 60s reencola los fichajes que aun no se enviaron (web caida, etc.)."""
    while True:
        time.sleep(60)
        try:
            with DBLOCK:
                pend = CON.execute(
                    "SELECT id FROM events WHERE sent=0 ORDER BY id").fetchall()
            for (rid,) in pend:
                SEND_Q.put(rid)
            if pend:
                log(f"reintento: reencolados {len(pend)} fichajes pendientes")
        except Exception as e:
            log(f"error en retry_worker: {e}")

# ---------------- SDK structs ----------------
class NET_TIME(Structure):
    _fields_=[("y",c_int),("mo",c_int),("d",c_int),("h",c_int),("mi",c_int),("s",c_int)]

class ALARM_ACCESS_CTL(Structure):
    _fields_=[("dwSize",c_int),("nDoor",c_int),("szDoorName",c_char*128),("stuTime",NET_TIME),
        ("emEventType",c_int),("bStatus",c_int),("emCardType",c_int),("emOpenMethod",c_int),
        ("szCardNo",c_char*32),("szPwd",c_char*64),("szReaderID",c_char*32),("szUserID",c_char*64),
        ("szSnapURL",c_char*256),("nErrorCode",c_int),("nPunchingRecNo",c_int),("nNumbers",c_int),
        ("emStatus",c_int),("szSN",c_char*32),("emAttendanceState",c_int),
        ("szQRCode",c_char*512),("szCallLiftFloor",c_char*16)]

class DEVINFO(Structure):
    _fields_=[("s",c_char*48),("a",c_int),("b",c_int),("c",c_int),("d",c_int),("ch",c_int),
              ("e",c_byte),("f",c_byte),("g",c_byte*2),("hh",c_int),("r",c_char*24)]
class LIN(Structure):
    _fields_=[("dwSize",c_uint),("szIP",c_char*64),("nPort",c_int),("szUserName",c_char*64),
              ("szPassword",c_char*64),("emSpecCap",c_int),("res",c_byte*4),("pCap",c_void_p)]
class LOUT(Structure):
    _fields_=[("dwSize",c_uint),("dev",DEVINFO),("nError",c_int),("res",c_byte*132)]

# ---------------- load SDK ----------------
os.chdir(SDK_DIR); os.add_dll_directory(SDK_DIR)
dll = ctypes.CDLL(os.path.join(SDK_DIR, "dhnetsdk.dll"))
dll.CLIENT_LoginWithHighLevelSecurity.restype = c_longlong
dll.CLIENT_Logout.argtypes = [c_longlong]
dll.CLIENT_SetDVRMessCallBack.argtypes = [c_void_p, c_void_p]
dll.CLIENT_SetAutoReconnect.argtypes = [c_void_p, c_void_p]
dll.CLIENT_StartListenEx.restype = c_int; dll.CLIENT_StartListenEx.argtypes = [c_longlong]
dll.CLIENT_StopListen.argtypes = [c_longlong]
dll.CLIENT_GetLastError.restype = c_uint

CON = db_init()

# message callback
MSG_CB_TYPE = WINFUNCTYPE(c_int, c_int, c_longlong, c_void_p, c_int, c_char_p, c_long, c_void_p)
def on_message(lCommand, lLoginID, pStuEvent, dwBufLen, strIP, nPort, dwUser):
    try:
        if lCommand == NET_ALARM_ACCESS_CTL_EVENT and pStuEvent:
            e = cast(pStuEvent, POINTER(ALARM_ACCESS_CTL)).contents
            t = e.stuTime
            if t.y < 2000:  # evento sin hora válida
                et = datetime.datetime.now()
            else:
                et = datetime.datetime(t.y, t.mo, t.d, t.h, t.mi, t.s)
            rec = (
                et.strftime("%Y-%m-%d %H:%M:%S"), et.strftime("%Y-%m-%d"),
                e.szUserID.decode(errors="ignore"), e.szCardNo.decode(errors="ignore"), "",
                e.emOpenMethod, METHOD.get(e.emOpenMethod, str(e.emOpenMethod)),
                1 if e.bStatus else 0, e.nDoor,
                e.emEventType, EVT.get(e.emEventType, ""),
                e.emAttendanceState, ATT.get(e.emAttendanceState, ""),
                DEV["ip"], datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
            rid = db_insert(CON, rec)
            log(f"FICHAJE user={rec[2]!r} card={rec[3]!r} {rec[0]} {rec[6]} {'OK' if rec[7] else 'FALLO'}")
            if rid and rt_is_configured():
                SEND_Q.put(rid)  # enviar a la web en tiempo real
    except Exception as ex:
        log(f"callback error: {ex}")
    return 1
MSG_CB = MSG_CB_TYPE(on_message)

# auto-reconnect callback
RECON_CB_TYPE = WINFUNCTYPE(None, c_longlong, c_char_p, c_long, c_void_p)
def on_reconnect(lLoginID, ip, port, user):
    log(f"RECONECTADO al equipo (handle={lLoginID})")
RECON_CB = RECON_CB_TYPE(on_reconnect)

# disconnect callback
DISC_CB_TYPE = WINFUNCTYPE(None, c_longlong, c_char_p, c_long, c_void_p)
def on_disconnect(lLoginID, ip, port, user):
    log("DESCONECTADO del equipo (intentando reconectar)...")
DISC_CB = DISC_CB_TYPE(on_disconnect)

def main():
    if rt_is_configured():
        threading.Thread(target=sender_worker, daemon=True).start()
        threading.Thread(target=retry_worker, daemon=True).start()
        log(f"Envio en tiempo real ACTIVADO -> {RT['url']}")
    else:
        log("Envio en tiempo real DESACTIVADO (revisa 'realtime' en config.json)")
    dll.CLIENT_Init(cast(DISC_CB, c_void_p), None)
    dll.CLIENT_SetAutoReconnect(cast(RECON_CB, c_void_p), None)
    dll.CLIENT_SetDVRMessCallBack(cast(MSG_CB, c_void_p), None)

    li = LIN(); li.dwSize = sizeof(LIN)
    li.szIP = DEV["ip"].encode(); li.nPort = DEV["port"]
    li.szUserName = DEV["user"].encode(); li.szPassword = DEV["password"].encode(); li.emSpecCap = 0

    h = 0
    while not h:
        lo = LOUT(); lo.dwSize = sizeof(LOUT)
        h = dll.CLIENT_LoginWithHighLevelSecurity(byref(li), byref(lo))
        if not h:
            log(f"login fallo err={hex(dll.CLIENT_GetLastError())}, reintentando en 10s")
            time.sleep(10)
    log(f"login OK handle={h}, serie={lo.dev.s.decode(errors='ignore')}")

    if not dll.CLIENT_StartListenEx(h):
        log(f"StartListenEx fallo err={hex(dll.CLIENT_GetLastError())}")
    else:
        log("Escuchando fichajes en tiempo real. Servicio activo.")

    # mantener vivo para siempre
    try:
        while True:
            time.sleep(3600)
            log("heartbeat: servicio activo")
    except KeyboardInterrupt:
        pass
    finally:
        dll.CLIENT_StopListen(h)
        dll.CLIENT_Logout(h)
        dll.CLIENT_Cleanup()

if __name__ == "__main__":
    log("=== Iniciando servicio de captura ===")
    main()
