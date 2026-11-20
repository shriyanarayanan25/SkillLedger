"""Create schema + functions. WARNING: drops the public schema (fresh start)."""
import pathlib
from db import connect
c = connect(autocommit=True); cur = c.cursor()
cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
for f in ("sql/01_schema.sql", "sql/02_matching.sql"):
    cur.execute(pathlib.Path(f).read_text()); print("applied", f)
print("Schema ready. Next: python seed.py --scale 0.05   (quick)  or  --scale 1  (>1M rows)")
