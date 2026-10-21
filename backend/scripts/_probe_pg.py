"""临时探针：探测本地 PostgreSQL 可用连接串（不修改任何状态）。"""
import os
import sys

sys.path.insert(0, r"D:\my-project\CrossPilot\backend\.venv\Lib\site-packages")

CANDIDATES = [
    "postgresql://postgres:postgres@127.0.0.1:5432/crosspilot",
    "postgresql://postgres:postgres@127.0.0.1:5432/postgres",
    "postgresql://postgres@127.0.0.1:5432/postgres",
    "postgresql://postgres:postgres@127.0.0.1:5432/crosspilot?sslmode=disable",
]

try:
    import psycopg
except Exception as e:
    print("IMPORT_FAIL", repr(e))
    sys.exit(2)

for url in CANDIDATES:
    try:
        c = psycopg.connect(url, connect_timeout=3)
        cur = c.cursor()
        cur.execute("select current_database(), version()")
        db, ver = cur.fetchone()
        print("OK", url, "->", db, ver[:50])
        c.close()
    except Exception as e:
        print("FAIL", url, "->", repr(e)[:160])
