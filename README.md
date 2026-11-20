# SkillLedger
ACID-compliant freelancing platform on PostgreSQL: double-entry escrow ledger with row-level locking,
recursive skill-graph matching, and pgvector semantic matching (RV College of Engineering, DBMS Lab).

## Run
```bash
pip install -r requirements.txt
docker compose up -d                  # PostgreSQL 16 + pgvector  (or use your own PG15+ with pgvector)
python setup_db.py                    # schema, triggers, stored procedures, matching functions
python seed.py --scale 0.05           # quick (~70k rows);  --scale 1  => ~1.45M rows
python demo_race.py                   # UNSAFE shows double payment, SAFE prevents it
python benchmark.py                   # latency without/with indexes + EXPLAIN ANALYZE of HNSW search
python evaluate.py                    # recursive vs semantic vs hybrid
streamlit run app.py                  # dashboard
```
Set `DATABASE_URL` if your DB differs from `postgresql://postgres:postgres@localhost:5432/skillledger`.

## Map to the synopsis phases
| Phase | Where |
|---|---|
| 1-2 Schema, 3NF, constraints, state-machine triggers, `fn_accept_proposal` | `sql/01_schema.sql` |
| 3 Escrow ledger + race condition | `fn_fund_milestone`, `fn_release_milestone(id, safe)`, `demo_race.py` |
| 4 Recursive CTE | `fn_graph_scores`, `fn_match_recursive` in `sql/02_matching.sql` |
| 5 pgvector + HNSW + hybrid score | `fn_match_semantic`, `fn_match_hybrid`, `sql/03_indexes.sql` |
| 6 Synthetic data + benchmarks | `seed.py`, `benchmark.py` |
| 7 Evaluation | `evaluate.py` |
| 8 GUI | `app.py` |

## Design notes
- **Ledger**: append-only; a deferred constraint trigger rejects any transaction whose legs don't sum to 0; wallets can't go negative; `v_wallet_reconciliation` audits cached balances against the ledger.
- **Race fix**: `SELECT ... FOR UPDATE` on the milestone row serialises releases; the loser re-reads `released` and aborts. Wallets are always locked in id order (no deadlocks). Extra safety: you can add `CREATE UNIQUE INDEX ON ledger_entries(milestone_id) WHERE kind='release' AND amount>0` (omitted so the unsafe demo can reproduce the bug).
- **Embeddings**: with `sentence-transformers` installed, skills use all-MiniLM-L6-v2. For speed, seeded freelancer/project vectors are the mean of their skill vectors (+noise); projects posted via the app are embedded from their real text. Without the library a hashing fallback runs (lexical, not truly semantic) - install the library for the semantic results.
- **Evaluation caveat**: `evaluate.py` uses the synthetic domain label as ground truth; replace with your hand-labelled pairs for the report.
- Taxonomy deliberately contains unlinked synonyms (e.g. "Server-side JavaScript") that only the vector search can connect.
