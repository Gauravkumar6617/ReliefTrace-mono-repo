"""
Snowflake connection pool.

The previous version held a single module-level connection behind a lock, so
every query in the app ran single-file - the dashboard's four "parallel"
queries actually executed one after another. This is a small fixed-size pool:
checkouts hand out an idle connection (or open one lazily up to
``SNOWFLAKE_POOL_SIZE``), so independent requests run concurrently.

Kept from before:
  - key-pair auth preferred, password auth as fallback;
  - a cooldown after a failed *connect* so a burst of traffic can't turn into
    a burst of failed logins that locks the Snowflake account.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from contextlib import contextmanager

import snowflake.connector
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization

from app.core.config import settings

log = logging.getLogger("relieftrace.db")

# After a failed connect, refuse to try again for this many seconds. Snowflake
# locks a user after 5 failed logins; this caps us at one failed login per
# window no matter how much traffic arrives.
_CONNECT_COOLDOWN_S = 30.0


def _connect_kwargs() -> dict:
    kwargs = dict(
        account=settings.snowflake_account,
        user=settings.snowflake_user,
        database=settings.snowflake_database,
        schema=settings.snowflake_schema,
        warehouse=settings.snowflake_warehouse,
        role=settings.snowflake_role,
        client_session_keep_alive=True,
    )

    key_path = settings.snowflake_private_key_path
    key_pem = settings.snowflake_private_key
    if key_path or key_pem:
        passphrase = settings.snowflake_private_key_passphrase
        if key_pem:
            # some host env-var UIs store multi-line values with literal "\n"
            pem_bytes = key_pem.replace("\\n", "\n").encode()
        else:
            with open(key_path, "rb") as fh:
                pem_bytes = fh.read()
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
        kwargs["password"] = settings.snowflake_password

    return kwargs


def _healthy(conn: snowflake.connector.SnowflakeConnection | None) -> bool:
    try:
        return conn is not None and not conn.is_closed()
    except Exception:
        return False


class SnowflakePool:
    def __init__(self, size: int) -> None:
        self._size = max(1, size)
        self._idle: queue.LifoQueue = queue.LifoQueue()
        self._lock = threading.Lock()
        self._opened = 0
        self._last_failure_at = 0.0
        self._last_failure_exc: Exception | None = None

    # -- internals ----------------------------------------------------
    def _open(self) -> snowflake.connector.SnowflakeConnection:
        # Fail fast during the cooldown after a bad login. startup prewarm()
        # makes the first connect happen alone, so a bad credential arms this
        # before real traffic arrives and can't rack up 5 failed logins.
        since = time.monotonic() - self._last_failure_at
        if self._last_failure_exc is not None and since < _CONNECT_COOLDOWN_S:
            log.warning("skipping Snowflake connect (cooldown, %.0fs left)", _CONNECT_COOLDOWN_S - since)
            raise self._last_failure_exc

        kw = _connect_kwargs()
        auth = "key-pair" if "private_key" in kw else "password"
        log.info("connecting to Snowflake account=%s user=%s auth=%s", kw.get("account"), kw.get("user"), auth)
        try:
            conn = snowflake.connector.connect(**kw)
            self._last_failure_exc = None
            log.info("Snowflake connection established")
            return conn
        except Exception as exc:
            self._last_failure_at = time.monotonic()
            self._last_failure_exc = exc
            log.error("Snowflake connect failed (%s auth): %s", auth, exc)
            raise

    def _acquire(self) -> snowflake.connector.SnowflakeConnection:
        while True:
            try:
                conn = self._idle.get_nowait()
                if _healthy(conn):
                    return conn
                with self._lock:
                    self._opened -= 1
                continue
            except queue.Empty:
                pass

            with self._lock:
                may_open = self._opened < self._size
                if may_open:
                    self._opened += 1
            if may_open:
                try:
                    return self._open()
                except Exception:
                    with self._lock:
                        self._opened -= 1
                    raise
            # pool exhausted - wait for a connection to come back
            conn = self._idle.get()
            if _healthy(conn):
                return conn
            with self._lock:
                self._opened -= 1

    def _release(self, conn: snowflake.connector.SnowflakeConnection, *, broken: bool) -> None:
        if broken or not _healthy(conn):
            try:
                conn.close()
            except Exception:
                pass
            with self._lock:
                self._opened -= 1
            return
        self._idle.put(conn)

    # -- public -----------------------------------------------------
    @contextmanager
    def cursor(self):
        conn = self._acquire()
        broken = False
        try:
            cur = conn.cursor(snowflake.connector.DictCursor)
            try:
                yield cur
            finally:
                cur.close()
        except snowflake.connector.Error:
            broken = True
            raise
        finally:
            self._release(conn, broken=broken)

    def prewarm(self) -> None:
        """Open one connection and run a trivial query so the first real
        request doesn't pay the cold TCP + auth + warehouse-resume tax."""
        try:
            with self.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchall()
            log.info("Snowflake pool prewarmed")
        except Exception as exc:  # noqa: BLE001 - best effort
            log.warning("Snowflake prewarm failed: %s", exc)

    def close(self) -> None:
        while True:
            try:
                self._idle.get_nowait().close()
            except queue.Empty:
                break
            except Exception:
                pass


pool = SnowflakePool(settings.snowflake_pool_size)


@contextmanager
def get_cursor():
    """Yield a DictCursor from the pool. Back-compat shim for existing call sites."""
    with pool.cursor() as cur:
        yield cur


def prewarm() -> None:
    pool.prewarm()
