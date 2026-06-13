import sqlite3, json, os
BASE = os.path.dirname(os.path.abspath(__file__))
c = json.load(open(os.path.join(BASE, "config.json"), encoding="utf-8"))
DB_PATH = c.get("db_path") or os.path.join(BASE, "attendance.db")
if not os.path.isdir(os.path.dirname(DB_PATH) or "."):
    DB_PATH = os.path.join(BASE, "attendance.db")
con = sqlite3.connect(DB_PATH)
total = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
hoy = con.execute("SELECT COUNT(*) FROM events WHERE event_date=date('now','localtime')").fetchone()[0]
print(f"Total fichajes en la base: {total}   (hoy: {hoy})")
rows = con.execute("""SELECT event_time, user_id, method_name,
                      CASE status WHEN 1 THEN 'OK' ELSE 'FALLO' END
                      FROM events ORDER BY id DESC LIMIT 8""").fetchall()
if rows:
    print("Ultimos fichajes:")
    for r in rows:
        print(f"   {r[0]}  user={r[1]:<6}  {r[2]:<10}  {r[3]}")
else:
    print("(aun no hay fichajes guardados)")
