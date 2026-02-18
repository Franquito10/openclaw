"""
ops.db — Database connection pool and helpers.

Uses psycopg (v3) if available, falls back to psycopg2.
Connection string from DATABASE_URL env var.
"""
import os
import json
import logging
from contextlib import contextmanager

log = logging.getLogger("ops.db")

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://openclaw:openclaw@127.0.0.1:5432/openclaw",
)

# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------
_pool = None


def _get_psycopg():
    """Import whichever psycopg is installed."""
    try:
        import psycopg
        return psycopg, 3
    except ImportError:
        pass
    try:
        import psycopg2
        return psycopg2, 2
    except ImportError:
        pass
    raise ImportError(
        "Neither psycopg (v3) nor psycopg2 is installed. "
        "Run: pip install psycopg2-binary   (or psycopg[binary])"
    )


def get_connection():
    """Return a new database connection."""
    mod, ver = _get_psycopg()
    conn = mod.connect(DATABASE_URL)
    if ver == 2:
        conn.autocommit = False
    return conn


@contextmanager
def db_cursor(autocommit=False):
    """
    Context manager yielding (conn, cursor).
    Commits on clean exit, rolls back on exception.
    """
    conn = get_connection()
    try:
        if autocommit:
            conn.autocommit = True
        cur = conn.cursor()
        yield conn, cur
        if not autocommit:
            conn.commit()
    except Exception:
        if not autocommit:
            conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def fetchone(sql, params=None):
    """Execute SQL, return one row as dict or None."""
    with db_cursor() as (conn, cur):
        cur.execute(sql, params or ())
        row = cur.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))


def fetchall(sql, params=None):
    """Execute SQL, return list of dicts."""
    with db_cursor() as (conn, cur):
        cur.execute(sql, params or ())
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def execute(sql, params=None):
    """Execute SQL (INSERT/UPDATE/DELETE), return rowcount."""
    with db_cursor() as (conn, cur):
        cur.execute(sql, params or ())
        return cur.rowcount


def execute_returning(sql, params=None):
    """Execute SQL with RETURNING, return single row as dict."""
    with db_cursor() as (conn, cur):
        cur.execute(sql, params or ())
        row = cur.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))


def emit_event(kind: str, source: str = None, payload: dict = None):
    """Insert an event into ops_events."""
    execute(
        "INSERT INTO ops_events (kind, source, payload) VALUES (%s, %s, %s)",
        (kind, source, json.dumps(payload) if payload else None),
    )


def get_policy(key: str, default=None):
    """Read a policy value (returns parsed JSON or default)."""
    row = fetchone("SELECT value FROM ops_policy WHERE key = %s", (key,))
    if row is None:
        return default
    val = row["value"]
    if isinstance(val, str):
        return json.loads(val)
    return val


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

def ping() -> bool:
    """Quick DB connectivity test."""
    try:
        row = fetchone("SELECT 1 AS ok")
        return row is not None and row.get("ok") == 1
    except Exception as e:
        log.warning("DB ping failed: %s", e)
        return False
