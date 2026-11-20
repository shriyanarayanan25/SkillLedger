-- SkillLedger schema (PostgreSQL 15+, pgvector)
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE users (
  user_id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE,
  role TEXT NOT NULL CHECK (role IN ('client','freelancer','admin')),
  hourly_rate NUMERIC(8,2) CHECK (hourly_rate > 0),
  available BOOLEAN NOT NULL DEFAULT TRUE,
  rating NUMERIC(3,2) NOT NULL DEFAULT 0 CHECK (rating BETWEEN 0 AND 5),
  bio TEXT,
  bio_embedding vector(384),
  domain TEXT,                       -- synthetic label, used only by evaluate.py
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE skills (
  skill_id SERIAL PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  domain TEXT,
  embedding vector(384)
);
CREATE TABLE skill_relations (            -- self-referencing skill graph
  parent_id INT NOT NULL REFERENCES skills ON DELETE CASCADE,
  child_id  INT NOT NULL REFERENCES skills ON DELETE CASCADE,
  PRIMARY KEY (parent_id, child_id),
  CHECK (parent_id <> child_id)
);
CREATE TABLE freelancer_skills (
  user_id INT NOT NULL REFERENCES users ON DELETE CASCADE,
  skill_id INT NOT NULL REFERENCES skills ON DELETE CASCADE,
  proficiency INT NOT NULL CHECK (proficiency BETWEEN 1 AND 5),
  PRIMARY KEY (user_id, skill_id)
);
CREATE TABLE projects (
  project_id SERIAL PRIMARY KEY,
  client_id INT NOT NULL REFERENCES users,
  title TEXT NOT NULL,
  description TEXT,
  budget NUMERIC(12,2) NOT NULL CHECK (budget > 0),
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','in_progress','completed','cancelled')),
  desc_embedding vector(384),
  domain TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE project_skills (
  project_id INT NOT NULL REFERENCES projects ON DELETE CASCADE,
  skill_id INT NOT NULL REFERENCES skills ON DELETE CASCADE,
  PRIMARY KEY (project_id, skill_id)
);
CREATE TABLE proposals (
  proposal_id SERIAL PRIMARY KEY,
  project_id INT NOT NULL REFERENCES projects ON DELETE CASCADE,
  freelancer_id INT NOT NULL REFERENCES users,
  bid NUMERIC(12,2) NOT NULL CHECK (bid > 0),
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','accepted','rejected','withdrawn')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (project_id, freelancer_id)
);
-- business rule enforced by the DB: at most ONE accepted proposal per project
CREATE UNIQUE INDEX uq_one_accepted_proposal ON proposals(project_id) WHERE status = 'accepted';

CREATE TABLE contracts (
  contract_id SERIAL PRIMARY KEY,
  proposal_id INT NOT NULL UNIQUE REFERENCES proposals,
  project_id INT NOT NULL UNIQUE REFERENCES projects,
  client_id INT NOT NULL REFERENCES users,
  freelancer_id INT NOT NULL REFERENCES users,
  total_amount NUMERIC(12,2) NOT NULL CHECK (total_amount > 0),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','completed','cancelled')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE milestones (
  milestone_id SERIAL PRIMARY KEY,
  contract_id INT NOT NULL REFERENCES contracts ON DELETE CASCADE,
  title TEXT NOT NULL,
  amount NUMERIC(12,2) NOT NULL CHECK (amount > 0),
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','funded','released','refunded')),
  released_at TIMESTAMPTZ
);
CREATE TABLE reviews (
  review_id SERIAL PRIMARY KEY,
  contract_id INT NOT NULL REFERENCES contracts,
  reviewer_id INT NOT NULL REFERENCES users,
  reviewee_id INT NOT NULL REFERENCES users,
  stars INT NOT NULL CHECK (stars BETWEEN 1 AND 5),
  comment TEXT,
  UNIQUE (contract_id, reviewer_id)
);
CREATE TABLE disputes (
  dispute_id SERIAL PRIMARY KEY,
  milestone_id INT NOT NULL REFERENCES milestones,
  raised_by INT NOT NULL REFERENCES users,
  reason TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved','rejected')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------- Escrow: wallets + double-entry ledger ----------
CREATE TABLE wallets (
  wallet_id SERIAL PRIMARY KEY,
  user_id INT UNIQUE REFERENCES users ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('user','escrow','platform','external')),
  balance NUMERIC(14,2) NOT NULL DEFAULT 0,
  CHECK (kind = 'external' OR balance >= 0)          -- no overdrafts
);
INSERT INTO wallets(wallet_id, kind) VALUES (1,'external'),(2,'escrow'),(3,'platform');
SELECT setval(pg_get_serial_sequence('wallets','wallet_id'), 3);

CREATE TABLE ledger_entries (                          -- append-only, signed amounts
  entry_id BIGSERIAL PRIMARY KEY,
  txn_id UUID NOT NULL,
  wallet_id INT NOT NULL REFERENCES wallets,
  milestone_id INT REFERENCES milestones,
  amount NUMERIC(14,2) NOT NULL CHECK (amount <> 0),
  kind TEXT NOT NULL CHECK (kind IN ('deposit','fund','release','fee','refund')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Every transaction's legs must sum to zero (checked at COMMIT)
CREATE FUNCTION fn_ledger_balanced() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF (SELECT sum(amount) FROM ledger_entries WHERE txn_id = NEW.txn_id) <> 0 THEN
    RAISE EXCEPTION 'unbalanced ledger transaction %', NEW.txn_id;
  END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER trg_ledger_balanced AFTER INSERT ON ledger_entries
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fn_ledger_balanced();

CREATE FUNCTION fn_ledger_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'ledger_entries is append-only'; END $$;
CREATE TRIGGER trg_ledger_immutable BEFORE UPDATE OR DELETE ON ledger_entries
  FOR EACH ROW EXECUTE FUNCTION fn_ledger_immutable();

-- auto-create a wallet for each new user
CREATE FUNCTION fn_new_user_wallet() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN INSERT INTO wallets(user_id, kind) VALUES (NEW.user_id, 'user'); RETURN NEW; END $$;
CREATE TRIGGER trg_user_wallet AFTER INSERT ON users
  FOR EACH ROW EXECUTE FUNCTION fn_new_user_wallet();

-- ---------- Status state machines ----------
CREATE TABLE status_transitions (entity TEXT, from_status TEXT, to_status TEXT, PRIMARY KEY (entity, from_status, to_status));
INSERT INTO status_transitions VALUES
 ('project','open','in_progress'),('project','open','cancelled'),
 ('project','in_progress','completed'),('project','in_progress','cancelled'),
 ('proposal','pending','accepted'),('proposal','pending','rejected'),('proposal','pending','withdrawn'),
 ('milestone','pending','funded'),('milestone','funded','released'),('milestone','funded','refunded'),
 ('contract','active','completed'),('contract','active','cancelled');

CREATE FUNCTION fn_check_transition() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM status_transitions
                 WHERE entity = TG_ARGV[0] AND from_status = OLD.status AND to_status = NEW.status) THEN
    RAISE EXCEPTION 'illegal % status transition: % -> %', TG_ARGV[0], OLD.status, NEW.status;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_project_status  BEFORE UPDATE ON projects  FOR EACH ROW WHEN (OLD.status IS DISTINCT FROM NEW.status) EXECUTE FUNCTION fn_check_transition('project');
CREATE TRIGGER trg_proposal_status BEFORE UPDATE ON proposals FOR EACH ROW WHEN (OLD.status IS DISTINCT FROM NEW.status) EXECUTE FUNCTION fn_check_transition('proposal');
CREATE TRIGGER trg_milestone_status BEFORE UPDATE ON milestones FOR EACH ROW WHEN (OLD.status IS DISTINCT FROM NEW.status) EXECUTE FUNCTION fn_check_transition('milestone');
CREATE TRIGGER trg_contract_status BEFORE UPDATE ON contracts FOR EACH ROW WHEN (OLD.status IS DISTINCT FROM NEW.status) EXECUTE FUNCTION fn_check_transition('contract');

-- ---------- Stored procedures ----------
-- Atomically accept ONE proposal, reject the rest, open a contract.
CREATE FUNCTION fn_accept_proposal(p_proposal INT) RETURNS INT LANGUAGE plpgsql AS $$
DECLARE r proposals%ROWTYPE; v_status TEXT; v_client INT; v_contract INT;
BEGIN
  SELECT * INTO r FROM proposals WHERE proposal_id = p_proposal;
  IF NOT FOUND THEN RAISE EXCEPTION 'proposal % not found', p_proposal; END IF;
  SELECT status, client_id INTO v_status, v_client FROM projects WHERE project_id = r.project_id FOR UPDATE;
  IF v_status <> 'open' THEN RAISE EXCEPTION 'project % is not open (%)', r.project_id, v_status; END IF;
  PERFORM 1 FROM proposals WHERE proposal_id = p_proposal AND status = 'pending' FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'proposal % is not pending', p_proposal; END IF;
  UPDATE proposals SET status = 'accepted' WHERE proposal_id = p_proposal;
  UPDATE proposals SET status = 'rejected' WHERE project_id = r.project_id AND proposal_id <> p_proposal AND status = 'pending';
  UPDATE projects SET status = 'in_progress' WHERE project_id = r.project_id;
  INSERT INTO contracts(proposal_id, project_id, client_id, freelancer_id, total_amount)
    VALUES (p_proposal, r.project_id, v_client, r.freelancer_id, r.bid) RETURNING contract_id INTO v_contract;
  RETURN v_contract;
END $$;

-- Money in from the outside world
CREATE FUNCTION fn_deposit(p_user INT, p_amount NUMERIC) RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE w INT; t UUID := gen_random_uuid();
BEGIN
  SELECT wallet_id INTO w FROM wallets WHERE user_id = p_user;
  PERFORM 1 FROM wallets WHERE wallet_id IN (1, w) ORDER BY wallet_id FOR UPDATE;
  INSERT INTO ledger_entries(txn_id, wallet_id, amount, kind) VALUES (t, 1, -p_amount, 'deposit'), (t, w, p_amount, 'deposit');
  UPDATE wallets SET balance = balance - p_amount WHERE wallet_id = 1;
  UPDATE wallets SET balance = balance + p_amount WHERE wallet_id = w;
END $$;

-- Client funds a milestone: client wallet -> escrow
CREATE FUNCTION fn_fund_milestone(p_milestone INT) RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE m milestones%ROWTYPE; v_client INT; w INT; t UUID := gen_random_uuid();
BEGIN
  SELECT * INTO m FROM milestones WHERE milestone_id = p_milestone FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'milestone % not found', p_milestone; END IF;
  IF m.status <> 'pending' THEN RAISE EXCEPTION 'milestone % is not pending (status=%)', p_milestone, m.status; END IF;
  SELECT client_id INTO v_client FROM contracts WHERE contract_id = m.contract_id;
  SELECT wallet_id INTO w FROM wallets WHERE user_id = v_client;
  PERFORM 1 FROM wallets WHERE wallet_id IN (2, w) ORDER BY wallet_id FOR UPDATE;
  IF (SELECT balance FROM wallets WHERE wallet_id = w) < m.amount THEN
    RAISE EXCEPTION 'insufficient funds in wallet %', w;
  END IF;
  INSERT INTO ledger_entries(txn_id, wallet_id, milestone_id, amount, kind)
    VALUES (t, w, p_milestone, -m.amount, 'fund'), (t, 2, p_milestone, m.amount, 'fund');
  UPDATE wallets SET balance = balance - m.amount WHERE wallet_id = w;
  UPDATE wallets SET balance = balance + m.amount WHERE wallet_id = 2;
  UPDATE milestones SET status = 'funded' WHERE milestone_id = p_milestone;
END $$;

-- Release escrow to the freelancer (5% platform fee).
-- p_safe = TRUE  : SELECT ... FOR UPDATE serialises concurrent releases  (the fix)
-- p_safe = FALSE : plain read + artificial delay, reproduces the double-payment race (demo only)
CREATE FUNCTION fn_release_milestone(p_milestone INT, p_safe BOOLEAN DEFAULT TRUE) RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE v_status TEXT; v_amount NUMERIC; v_contract INT; v_freelancer INT; w INT;
        v_fee NUMERIC; v_pay NUMERIC; t UUID := gen_random_uuid();
BEGIN
  IF p_safe THEN
    SELECT status, amount, contract_id INTO v_status, v_amount, v_contract FROM milestones WHERE milestone_id = p_milestone FOR UPDATE;
  ELSE
    SELECT status, amount, contract_id INTO v_status, v_amount, v_contract FROM milestones WHERE milestone_id = p_milestone;
    PERFORM pg_sleep(0.5);
  END IF;
  IF v_status IS NULL THEN RAISE EXCEPTION 'milestone % not found', p_milestone; END IF;
  IF v_status <> 'funded' THEN RAISE EXCEPTION 'milestone % is not funded (status=%)', p_milestone, v_status; END IF;
  SELECT freelancer_id INTO v_freelancer FROM contracts WHERE contract_id = v_contract;
  SELECT wallet_id INTO w FROM wallets WHERE user_id = v_freelancer;
  v_fee := round(v_amount * 0.05, 2);  v_pay := v_amount - v_fee;
  PERFORM 1 FROM wallets WHERE wallet_id IN (2, 3, w) ORDER BY wallet_id FOR UPDATE;
  INSERT INTO ledger_entries(txn_id, wallet_id, milestone_id, amount, kind) VALUES
    (t, 2, p_milestone, -v_amount, 'release'),
    (t, w, p_milestone,  v_pay,    'release'),
    (t, 3, p_milestone,  v_fee,    'fee');
  UPDATE wallets SET balance = balance - v_amount WHERE wallet_id = 2;
  UPDATE wallets SET balance = balance + v_pay    WHERE wallet_id = w;
  UPDATE wallets SET balance = balance + v_fee    WHERE wallet_id = 3;
  UPDATE milestones SET status = 'released', released_at = now() WHERE milestone_id = p_milestone;
  IF NOT EXISTS (SELECT 1 FROM milestones WHERE contract_id = v_contract AND status <> 'released') THEN
    UPDATE contracts SET status = 'completed' WHERE contract_id = v_contract AND status = 'active';
    UPDATE projects SET status = 'completed' WHERE project_id = (SELECT project_id FROM contracts WHERE contract_id = v_contract) AND status = 'in_progress';
  END IF;
END $$;

-- Audit: cached wallet balance must equal the sum of its ledger entries
CREATE VIEW v_wallet_reconciliation AS
SELECT w.wallet_id, w.kind, w.balance,
       COALESCE(SUM(l.amount), 0) AS ledger_sum,
       w.balance = COALESCE(SUM(l.amount), 0) AS ok
FROM wallets w LEFT JOIN ledger_entries l USING (wallet_id)
GROUP BY w.wallet_id, w.kind, w.balance;
