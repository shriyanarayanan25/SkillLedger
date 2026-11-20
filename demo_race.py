"""Double-payment race: two concurrent releases of the same milestone, unsafe vs FOR UPDATE."""
import threading, uuid
from db import connect, q

def setup():
    c = connect(autocommit=True); cur = c.cursor(); tag = uuid.uuid4().hex[:8]
    ids = []
    for role in ("client", "freelancer"):
        cur.execute("INSERT INTO users(name,email,role,hourly_rate) VALUES (%s,%s,%s,%s) RETURNING user_id",
                    (f"demo {role}", f"{role}-{tag}@demo.test", role, 50 if role == "freelancer" else None))
        ids.append(cur.fetchone()[0])
    cl, fr = ids
    cur.execute("SELECT fn_deposit(%s, 1000)", (cl,))
    cur.execute("INSERT INTO projects(client_id,title,budget) VALUES (%s,'race demo',200) RETURNING project_id", (cl,))
    pid = cur.fetchone()[0]
    cur.execute("INSERT INTO proposals(project_id,freelancer_id,bid) VALUES (%s,%s,200) RETURNING proposal_id", (pid, fr))
    prop = cur.fetchone()[0]
    cur.execute("SELECT fn_accept_proposal(%s)", (prop,)); con = cur.fetchone()[0]
    ms = []
    for title in ("target milestone", "decoy (keeps escrow solvent)"):   # decoy: escrow holds other money, like production
        cur.execute("INSERT INTO milestones(contract_id,title,amount) VALUES (%s,%s,100) RETURNING milestone_id", (con, title))
        m = cur.fetchone()[0]; cur.execute("SELECT fn_fund_milestone(%s)", (m,)); ms.append(m)
    cur.execute("SELECT wallet_id FROM wallets WHERE user_id=%s", (fr,)); fw = cur.fetchone()[0]
    return ms[0], fw

def race(safe: bool):
    m, fw = setup(); out = [None, None]; bar = threading.Barrier(2)
    def worker(i):
        c = connect()
        try:
            cur = c.cursor(); bar.wait(); cur.execute("SELECT fn_release_milestone(%s, %s)", (m, safe)); c.commit(); out[i] = "OK: released"
        except Exception as e:
            c.rollback(); out[i] = "REJECTED: " + str(e).splitlines()[0]
        finally: c.close()
    ts = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    [t.start() for t in ts]; [t.join() for t in ts]
    payouts = int(q("SELECT count(*) n FROM ledger_entries WHERE milestone_id=%s AND wallet_id=%s AND kind='release'", (m, fw)).n[0])
    bal = float(q("SELECT balance FROM wallets WHERE wallet_id=%s", (fw,)).balance[0])
    return {"mode": "SAFE (FOR UPDATE)" if safe else "UNSAFE (no lock)", "request_1": out[0], "request_2": out[1],
            "payouts_for_one_milestone": payouts, "freelancer_balance": bal, "expected_balance": 95.0,
            "double_payment": payouts > 1}

if __name__ == "__main__":
    for s in (False, True): print(race(s))
