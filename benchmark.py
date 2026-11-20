"""Latency of recursive / semantic / hybrid matching with and without indexes."""
import pathlib, statistics, time
from db import connect, q
IDX = ["idx_fs_skill","idx_rel_parent","idx_ps_skill","idx_users_avail","idx_users_hnsw","idx_projects_hnsw"]
projs = q("SELECT project_id FROM projects WHERE status='open' ORDER BY project_id LIMIT 8").project_id.tolist()
FUNCS = {"recursive": "fn_match_recursive", "semantic": "fn_match_semantic", "hybrid": "fn_match_hybrid"}

def timeit():
    res = {}
    for k, f in FUNCS.items():
        ts = []
        for p in projs:
            c = connect(autocommit=True); cur = c.cursor(); t = time.perf_counter()
            cur.execute(f"SELECT * FROM {f}(%s, 20)", (p,)); cur.fetchall(); ts.append((time.perf_counter() - t) * 1000); c.close()
        res[k] = statistics.median(ts)
    return res

c = connect(autocommit=True); cur = c.cursor()
for i in IDX: cur.execute(f"DROP INDEX IF EXISTS {i}")
before = timeit()
cur.execute(pathlib.Path("sql/03_indexes.sql").read_text()); cur.execute("ANALYZE")
after = timeit()
print(f"{'query':<11}{'no index (ms)':>15}{'indexed (ms)':>15}{'speedup':>9}")
for k in FUNCS: print(f"{k:<11}{before[k]:>15.1f}{after[k]:>15.1f}{before[k]/after[k]:>8.1f}x")
print("\nEXPLAIN ANALYZE (vector search):")
cur.execute("""EXPLAIN (ANALYZE, BUFFERS) SELECT user_id FROM users WHERE role='freelancer'
  ORDER BY bio_embedding <=> (SELECT desc_embedding FROM projects WHERE project_id=%s) LIMIT 20""", (projs[0],))
print("\n".join(r[0] for r in cur.fetchall()))
