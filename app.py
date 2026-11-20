import time, streamlit as st, pandas as pd
from db import q, run, connect
from embed import embed, vec_literal, backend
import demo_race

st.set_page_config(page_title="SkillLedger", page_icon="💼", layout="wide")
st.title("💼 SkillLedger")
st.caption(f"ACID escrow ledger · recursive skill graph · pgvector semantic matching  |  embeddings: {backend()}")
tab1, tab2, tab3, tab4 = st.tabs(["1 · Post project", "2 · Ranked matches", "3 · Contract & escrow", "4 · Race-condition demo"])

with tab1:
    clients = q("SELECT user_id, name FROM users WHERE role='client' ORDER BY user_id LIMIT 200")
    skills = q("SELECT skill_id, name FROM skills ORDER BY name")
    c = st.selectbox("Client", clients.user_id, format_func=lambda i: f"{i} · {clients.set_index('user_id').name[i]}")
    title = st.text_input("Title", "Build a single-page web app")
    desc = st.text_area("Description", "We need someone who knows server-side JavaScript and modern frontend frameworks.")
    budget = st.number_input("Budget", 100, 100000, 1500)
    sel = st.multiselect("Required skills", skills.name.tolist(), default=["Frontend"])
    if st.button("Post project") and sel:
        e = embed(f"{title}. {desc}. Skills: {', '.join(sel)}")[0]
        pid = run("INSERT INTO projects(client_id,title,description,budget,desc_embedding) VALUES (%s,%s,%s,%s,%s::vector) RETURNING project_id",
                  (int(c), title, desc, budget, vec_literal(e)))[0]
        for s in sel: run("INSERT INTO project_skills SELECT %s, skill_id FROM skills WHERE name=%s", (pid, s))
        st.success(f"Project #{pid} posted. Open tab 2 to see matches.")

with tab2:
    pr = q("SELECT project_id, title FROM projects WHERE status='open' ORDER BY project_id DESC LIMIT 50")
    pid = st.selectbox("Project", pr.project_id, format_func=lambda i: f"#{i} · {pr.set_index('project_id').title[i]}", key="mp")
    st.write("**Required skills:**", ", ".join(q("SELECT s.name FROM project_skills ps JOIN skills s USING(skill_id) WHERE project_id=%s", (int(pid),)).name))
    c1, c2, c3 = st.columns(3)
    wg = c1.slider("Graph weight", 0.0, 1.0, 0.4); ws = c2.slider("Semantic weight", 0.0, 1.0, 0.4); wr = c3.slider("Rating weight", 0.0, 0.5, 0.1)
    cols = st.columns(3)
    for col, (label, sql, args) in zip(cols, [
        ("Recursive graph only", "SELECT * FROM fn_match_recursive(%s,10)", (int(pid),)),
        ("Semantic (pgvector) only", "SELECT * FROM fn_match_semantic(%s,10)", (int(pid),)),
        ("Hybrid", "SELECT * FROM fn_match_hybrid(%s,10,%s,%s,%s)", (int(pid), wg, ws, wr))]):
        t = time.perf_counter(); df = q(sql, args); ms = (time.perf_counter() - t) * 1000
        col.subheader(label); col.caption(f"{ms:.0f} ms"); col.dataframe(df.round(3), hide_index=True, use_container_width=True)

with tab3:
    pid = st.number_input("Project id", 1, value=int(pr.project_id.iloc[0]) if len(pr) else 1, key="ep")
    props = q("SELECT proposal_id, freelancer_id, bid, status FROM proposals WHERE project_id=%s ORDER BY proposal_id", (int(pid),))
    st.subheader("Proposals"); st.dataframe(props, hide_index=True)
    pending = props[props.status == "pending"].proposal_id.tolist()
    if pending:
        pp = st.selectbox("Accept proposal", pending)
        if st.button("Accept (atomic: rejects the others, opens contract)"):
            try: st.success(f"Contract #{run('SELECT fn_accept_proposal(%s)', (int(pp),))[0]} created"); st.rerun()
            except Exception as e: st.error(str(e).splitlines()[0])
    ct = q("SELECT * FROM contracts WHERE project_id=%s", (int(pid),))
    if len(ct):
        cid = int(ct.contract_id[0]); st.subheader(f"Contract #{cid}"); st.dataframe(ct, hide_index=True)
        a, b, cc = st.columns(3)
        mt = a.text_input("Milestone title", "Milestone 1"); ma = b.number_input("Amount", 1, 100000, 100)
        if cc.button("Add milestone"): run("INSERT INTO milestones(contract_id,title,amount) VALUES (%s,%s,%s)", (cid, mt, ma)); st.rerun()
        ms = q("SELECT milestone_id, title, amount, status FROM milestones WHERE contract_id=%s ORDER BY 1", (cid,)); st.dataframe(ms, hide_index=True)
        if len(ms):
            m = int(st.selectbox("Milestone", ms.milestone_id)); x, y = st.columns(2)
            if x.button("💰 Fund into escrow"):
                try: run("SELECT fn_fund_milestone(%s)", (m,)); st.rerun()
                except Exception as e: st.error(str(e).splitlines()[0])
            if y.button("✅ Release payment"):
                try: run("SELECT fn_release_milestone(%s)", (m,)); st.rerun()
                except Exception as e: st.error(str(e).splitlines()[0])
        st.subheader("Ledger (double-entry)")
        st.dataframe(q("SELECT entry_id, txn_id, wallet_id, milestone_id, amount, kind FROM ledger_entries WHERE milestone_id IN (SELECT milestone_id FROM milestones WHERE contract_id=%s) ORDER BY entry_id", (cid,)), hide_index=True)
    st.subheader("Wallet reconciliation (cached balance vs ledger sum)")
    st.dataframe(q("SELECT * FROM v_wallet_reconciliation WHERE wallet_id <= 3 OR wallet_id IN (SELECT wallet_id FROM ledger_entries WHERE milestone_id IS NOT NULL) ORDER BY wallet_id LIMIT 50"), hide_index=True)

with tab4:
    st.write("Two sessions release the **same funded milestone** at the same instant. Expected: freelancer is paid once (95.00 after the 5% fee).")
    l, r = st.columns(2)
    if l.button("▶ Run UNSAFE (no row lock)"): l.json(demo_race.race(False))
    if r.button("▶ Run SAFE (SELECT … FOR UPDATE)"): r.json(demo_race.race(True))
