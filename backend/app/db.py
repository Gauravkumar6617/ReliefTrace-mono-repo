"""
Snowflake connection helper.

Previously this opened a fresh connection per request, which meant every API
call paid a 2-4s TCP + auth + warehouse-resume tax. Now we hold one module
-level connection, guarded by a lock, and transparently reconnect if it has
dropped or gone stale. Good enough for a single-process demo; for multiple
workers you'd want a real pool (see the TODO in main.py).
"""

import os
import threading
from contextlib import contextmanager

import snowflake.connector
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from dotenv import load_dotenv

load_dotenv()

_conn: snowflake.connector.SnowflakeConnection | None = None
_lock = threading.Lock()


def _connect_kwargs() -> dict:
    kwargs = dict(
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        user=os.getenv("SNOWFLAKE_USER"),
        database=os.getenv("SNOWFLAKE_DATABASE", "RELIEFTRACE_DB"),
        schema=os.getenv("SNOWFLAKE_SCHEMA", "PUBLIC"),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE", "GENEROSITY_WH"),
        role=os.getenv("SNOWFLAKE_ROLE") or None,
        client_session_keep_alive=True,  # keeps the session warm between calls
    )

    key_path = os.getenv("SNOWFLAKE_PRIVATE_KEY_PATH")
    if key_path:
        passphrase = os.getenv("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE")
        with open(key_path, "rb") as f:
            private_key = serialization.load_pem_private_key(
                f.read(),
                password=passphrase.encode() if passphrase else None,
                backend=default_backend(),
            )
        kwargs["private_key"] = private_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    else:
        # MFA-enforced users will fail here - see SNOWFLAKE_PRIVATE_KEY_PATH above
        kwargs["password"] = os.getenv("SNOWFLAKE_PASSWORD")

    return kwargs


def _healthy(conn: snowflake.connector.SnowflakeConnection | None) -> bool:
    if conn is None:
        return False
    try:
        return not conn.is_closed()
    except Exception:
        return False


def _get_connection() -> snowflake.connector.SnowflakeConnection:
    global _conn
    with _lock:
        if not _healthy(_conn):
            _conn = snowflake.connector.connect(**_connect_kwargs())
        return _conn


@contextmanager
def get_cursor():
    """Yield a cursor on the shared connection. Reconnects once on failure."""
    try:
        conn = _get_connection()
        cur = conn.cursor(snowflake.connector.DictCursor)
    except snowflake.connector.Error:
        # force a fresh connection and try one more time
        global _conn
        with _lock:
            _conn = None
        conn = _get_connection()
        cur = conn.cursor(snowflake.connector.DictCursor)

    try:
        yield cur
    finally:
        cur.close()
