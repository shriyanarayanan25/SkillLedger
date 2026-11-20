"""Compare recursive-only / semantic-only / hybrid. Ground truth = synthetic domain label
(freelancer.domain == project.domain). Swap in hand-labelled pairs for the report if required."""
import random
from db import q
random.seed(1)
ids = q("SELECT project_id, domain FROM projects WHERE status='open' ORDER BY project_id LIMIT 400")
sample = ids.sample(min(40, len(ids)), random_state=1)
K = 20; stats = {m: {"p": [], "sem_only_hits": []} for m in ("recursive", "semantic", "hybrid")}
for pid, dom in zip(sample.project_id, sample.domain):
    for m in stats:
        r = q(f"SELECT m.*, u.domain FROM fn_match_{m}(%s, {K}) m JOIN users u USING (user_id)", (int(pid),))
        rel = (r.domain == dom)
        stats[m]["p"].append(rel.mean() if len(r) else 0)
        stats[m]["sem_only_hits"].append(((r.graph_score == 0) & rel).sum())   # relevant freelancers the skill graph did NOT reach
print(f"projects evaluated: {len(sample)}   K={K}")
print(f"{'method':<11}{'precision@K':>13}{'graph-missed relevant hits':>30}")
for m, s in stats.items(): print(f"{m:<11}{sum(s['p'])/len(s['p']):>13.3f}{sum(s['sem_only_hits'])/len(s['sem_only_hits']):>30.2f}")
