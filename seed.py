"""Synthetic data. --scale 1 => ~1.45M rows (100k users, 100k projects, 450k freelancer_skills, ...)."""
import argparse, csv, io, pathlib, random, uuid, time
import numpy as np
from faker import Faker
from db import connect
from embed import embed, vec_literal, backend, DIM
from taxonomy import DOMAINS, SYNONYMS, domain_skills

ap = argparse.ArgumentParser(); ap.add_argument("--scale", type=float, default=1.0); a = ap.parse_args()
N_USERS, N_PROJ = int(100_000 * a.scale), int(100_000 * a.scale)
rng = np.random.default_rng(42); random.seed(42); fake = Faker(); Faker.seed(42)
conn = connect(); cur = conn.cursor(); t0 = time.time()

def copy(table, cols, rows):
    buf = io.StringIO(); w = csv.writer(buf); n = 0
    for r in rows: w.writerow(["\\N" if x is None else x for x in r]); n += 1
    buf.seek(0)
    cur.copy_expert(f"COPY {table} ({cols}) FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf); return n

def chunks(n, size=10_000):
    for s in range(0, n, size): yield s, min(n, s + size)

total = 0
cur.execute("TRUNCATE users, skills, projects, wallets, ledger_entries RESTART IDENTITY CASCADE")
cur.execute("INSERT INTO wallets(wallet_id, kind) VALUES (1,'external'),(2,'escrow'),(3,'platform')")
cur.execute("ALTER TABLE users DISABLE TRIGGER USER; ALTER TABLE ledger_entries DISABLE TRIGGER USER")

# ---- skills + graph
print("embedding backend:", backend())
names, dom_of = [], {}
for d in DOMAINS:
    for s in domain_skills(d): names.append(s); dom_of[s] = d
sid = {n: i + 1 for i, n in enumerate(names)}
E = embed(names)
total += copy("skills", "skill_id,name,domain,embedding", [(sid[n], n, dom_of[n], vec_literal(E[sid[n]-1])) for n in names])
rels = {(sid[p], sid[c]) for d in DOMAINS for p, cs in DOMAINS[d].items() for c in cs}
total += copy("skill_relations", "parent_id,child_id", sorted(rels))
dskills = {d: np.array([sid[s] for s in domain_skills(d)]) for d in DOMAINS}
dparents = {d: [sid[p] for p in DOMAINS[d]] for d in DOMAINS}
domains = list(DOMAINS)

def profile_vec(idx):           # profile embedding = mean of skill embeddings + small noise
    m = E[np.array(idx) - 1].mean(0) + rng.normal(0, 0.02, DIM)
    return (m / np.linalg.norm(m)).astype(np.float32)

# ---- users, freelancer_skills, wallets, deposit ledger
n_clients = N_USERS // 10
for s, e in chunks(N_USERS):
    urows, fsrows, wrows, lrows = [], [], [], []
    for u in range(s + 1, e + 1):
        is_client = u <= n_clients
        d = random.choice(domains)
        if is_client:
            urows.append((u, fake.name(), f"user{u}@example.com", "client", None, True, 0, fake.catch_phrase(), None, None))
        else:
            sk = random.sample(list(dskills[d]), 5)
            fsrows += [(u, k, random.randint(1, 5)) for k in sk]
            bio = "Freelancer experienced in " + ", ".join(names[k-1] for k in sk) + "."
            urows.append((u, fake.name(), f"user{u}@example.com", "freelancer", round(random.uniform(8, 90), 2),
                          random.random() < 0.8, round(random.uniform(2.5, 5), 2), bio, vec_literal(profile_vec(sk)), d))
        wrows.append((3 + u, u, "user", 5000)); t = str(uuid.uuid4())
        lrows += [(t, 1, -5000, "deposit"), (t, 3 + u, 5000, "deposit")]
    total += copy("users", "user_id,name,email,role,hourly_rate,available,rating,bio,bio_embedding,domain", urows)
    total += copy("freelancer_skills", "user_id,skill_id,proficiency", fsrows)
    total += copy("wallets", "wallet_id,user_id,kind,balance", wrows)
    total += copy("ledger_entries", "txn_id,wallet_id,amount,kind", lrows)
    print(f"users {e}/{N_USERS}", end="\r")
cur.execute("UPDATE wallets SET balance = -5000::numeric * %s WHERE wallet_id = 1", (N_USERS,))

# ---- projects, project_skills, proposals
for s, e in chunks(N_PROJ):
    prow, psrow, porow = [], [], []
    for p in range(s + 1, e + 1):
        d = random.choice(domains); k = random.randint(2, 3)
        sk = [random.choice(dparents[d]) if random.random() < .6 else int(random.choice(dskills[d])) for _ in range(k)]
        sk = list(dict.fromkeys(sk)); lst = ", ".join(names[x-1] for x in sk)
        prow.append((p, random.randint(1, n_clients), f"Need help with {names[sk[0]-1]}", f"Looking for an expert in {lst}.",
                     random.randint(200, 5000), "open", vec_literal(profile_vec(sk)), d))
        psrow += [(p, x) for x in sk]
        f0 = random.randint(n_clients + 1, N_USERS)
        for i in range(2):
            f = n_clients + 1 + (f0 - n_clients - 1 + i * 7919) % (N_USERS - n_clients)
            porow.append((p, f, random.randint(100, 4000)))
    total += copy("projects", "project_id,client_id,title,description,budget,status,desc_embedding,domain", prow)
    total += copy("project_skills", "project_id,skill_id", psrow)
    total += copy("proposals", "project_id,freelancer_id,bid", porow)
    print(f"projects {e}/{N_PROJ}", end="\r")

for t, c in [("users","user_id"),("skills","skill_id"),("projects","project_id"),("wallets","wallet_id"),("proposals","proposal_id"),("ledger_entries","entry_id")]:
    cur.execute(f"SELECT setval(pg_get_serial_sequence('{t}','{c}'), (SELECT max({c}) FROM {t}))")
cur.execute("ALTER TABLE users ENABLE TRIGGER USER; ALTER TABLE ledger_entries ENABLE TRIGGER USER")
conn.commit(); print(f"\nloaded ~{total:,} rows in {time.time()-t0:.0f}s; building indexes...")
cur.execute(pathlib.Path("sql/03_indexes.sql").read_text()); conn.commit()
conn.autocommit = True; cur.execute("ANALYZE"); print("done.")
