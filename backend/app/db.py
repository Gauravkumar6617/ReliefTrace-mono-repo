"""
Snowflake connection helper.

Previously this opened a fresh connection per request, which meant every API
call paid a 2-4s TCP + auth + warehouse-resume tax. Now we hold one module
-level connection, guarded by a lock, and transparently reconnect if it has
dropped or gone stale. Good enough for a single-process demo; for multiple
workers you'd want a real pool (see the TODO in main.py).
"""

import logging
import os
import threading
import time
from contextlib import contextmanager

import snowflake.connector
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("relieftrace.db")

_conn: snowflake.connector.SnowflakeConnection | None = None
_lock = threading.Lock()

# After a failed connect, refuse to try again for this many seconds. Without
# this, one dashboard load (~6 API calls) becomes ~6 failed Snowflake logins,
# which locks the account after 5. The cooldown means at most one failed login
# per 30s no matter how much traffic hits the API.
_CONNECT_COOLDOWN_S = 30.0
_last_failure_at = 0.0
_last_failure_exc: Exception | None = None


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

    # Key-pair auth. Locally the PEM lives in a file (SNOWFLAKE_PRIVATE_KEY_PATH);
    # on a host where keys/ isn't uploaded, pass the PEM text itself in
    # SNOWFLAKE_PRIVATE_KEY. Either one enables key-pair auth; otherwise we fall
    # back to password auth.
    key_path = os.getenv("SNOWFLAKE_PRIVATE_KEY_PATH")
    key_pem = os.getenv("SNOWFLAKE_PRIVATE_KEY")
    if key_path or key_pem:
        passphrase = os.getenv("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE")
        if key_pem:
            # some host env-var UIs store multi-line values with literal "\n"
            pem_bytes = key_pem.replace("\\n", "\n").encode()
        else:
            pem_bytes = open(key_path, "rb").read()
        private_key = serialization.load_pem_private_key(
            pem_bytes,
            password=passphrase.encode() if passphrase else None,
            backend=default_backend(),
        )
        kwargs["private_key"] = private_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    else:
        # MFA-enforced users will fail here - use key-pair auth above instead
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
    global _conn, _last_failure_at, _last_failure_exc
    with _lock:
        if _healthy(_conn):
            return _conn

        # still inside the cooldown after a recent failure - fail fast, don't
        # hit Snowflake again (that's what locks the account)
        since = time.monotonic() - _last_failure_at
        if _last_failure_exc is not None and since < _CONNECT_COOLDOWN_S:
            log.warning("skipping Snowflake connect (cooldown, %.0fs left)", _CONNECT_COOLDOWN_S - since)
            raise _last_failure_exc

        kw = _connect_kwargs()
        auth = "key-pair" if "private_key" in kw else "password"
        log.info("connecting to Snowflake account=%s user=%s auth=%s", kw.get("account"), kw.get("user"), auth)
        try:
            _conn = snowflake.connector.connect(**kw)
            _last_failure_exc = None
            log.info("Snowflake connection established")
            return _conn
        except Exception as exc:
            _last_failure_at = time.monotonic()
            _last_failure_exc = exc
            log.error("Snowflake connect failed (%s auth): %s", auth, exc)
            raise


@contextmanager
def get_cursor():
    """Yield a cursor on the shared connection. One reconnect on a *stale*
    connection; never a blind retry on an auth/connect failure (see cooldown)."""
    conn = _get_connection()
    try:
        cur = conn.cursor(snowflake.connector.DictCursor)
    except snowflake.connector.Error:
        # the pooled connection went stale between requests - drop and rebuild once
        global _conn
        with _lock:
            _conn = None
        conn = _get_connection()
        cur = conn.cursor(snowflake.connector.DictCursor)

    try:
        yield cur
    finally:
        cur.close()
