import os, psycopg2, pandas as pd
DSN = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/skillledger")

def connect(autocommit=False):
    c = psycopg2.connect(DSN); c.autocommit = autocommit; return c

def q(sql, params=None):
    """Run a query, return a DataFrame."""
    with connect() as c, c.cursor() as cur:
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=cols)

def run(sql, params=None):
    """Run a statement in its own transaction; return first row if any."""
    with connect() as c, c.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone() if cur.description else None
