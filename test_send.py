"""
Prueba el envio en tiempo real SIN necesidad del terminal Dahua.
Manda un fichaje de ejemplo a tu endpoint web (config.json -> realtime.url)
exactamente con el mismo formato JSON que usa capture_service.py.

Uso:
    python test_send.py            # manda un fichaje de prueba (inventado)
    python test_send.py --real     # manda el ULTIMO fichaje real de attendance.db
"""
import os, json, sys, sqlite3, datetime
import urllib.request, urllib.error

BASE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(BASE, "config.json"), encoding="utf-8"))
RT = CFG.get("realtime", {})
DB_PATH = CFG.get("db_path") or os.path.join(BASE, "attendance.db")
if not os.path.isdir(os.path.dirname(DB_PATH) or "."):
    DB_PATH = os.path.join(BASE, "attendance.db")

SEND_COLS = ["id","event_time","event_date","user_id","card_no","method","method_name",
             "status","door","direction","direction_name","attendance_state",
             "attendance_name","device_ip","captured_at"]

def sample_payload():
    now = datetime.datetime.now()
    return {
        "id": 0,
        "event_time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "event_date": now.strftime("%Y-%m-%d"),
        "user_id": "TEST001",
        "card_no": "1234567890",
        "method": 7,
        "method_name": "Huella",
        "status": 1,
        "door": 1,
        "direction": 1,
        "direction_name": "Entrada",
        "attendance_state": 1,
        "attendance_name": "Entrada",
        "device_ip": CFG.get("device", {}).get("ip", ""),
        "captured_at": now.strftime("%Y-%m-%d %H:%M:%S"),
    }

def last_real_payload():
    con = sqlite3.connect(DB_PATH)
    row = con.execute(
        f"SELECT {','.join(SEND_COLS)} FROM events ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        print("No hay fichajes en attendance.db; usa el modo de prueba sin --real.")
        sys.exit(1)
    return dict(zip(SEND_COLS, row))

def main():
    payload = last_real_payload() if "--real" in sys.argv else sample_payload()
    print("Enviando este fichaje:")
    print(json.dumps(payload, indent=2, ensure_ascii=False))

    url = RT.get("url", "")
    if not url or "TU-SISTEMA-WEB" in url:
        print("\n[!] Configura primero 'realtime.url' en config.json con tu URL real.")
        sys.exit(1)

    headers = {"Content-Type": "application/json"}
    auth = RT.get("auth_value", "")
    if RT.get("auth_header") and auth and "PON-TU-TOKEN" not in auth:
        headers[RT["auth_header"]] = RT["auth_value"]

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=RT.get("timeout", 10)) as r:
                code, body = r.getcode(), r.read().decode(errors="ignore")
        except urllib.error.HTTPError as e:
            code, body = e.code, e.read().decode(errors="ignore")
        print(f"\nRespuesta de tu web: HTTP {code}")
        print(body[:500])
        if 200 <= code < 300:
            print("\nOK -> tu web acepto el fichaje. Revisa que aparezca en tu BD MySQL.")
        else:
            print("\n[!] Tu web no respondio 2xx. Revisa el endpoint / token.")
    except Exception as e:
        print(f"\n[!] No se pudo conectar a tu web: {e}")

if __name__ == "__main__":
    main()
