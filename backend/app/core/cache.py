"""
Cache for the read-only insight endpoints.

Two-tier and best-effort:
  - if REDIS_URL is set and reachable, results are cached there (survives
    backend restarts - the main win on a host that recycles processes or
    scales to zero, where the warehouse goes cold between runs);
  - otherwise, and whenever Redis errors mid-request, it falls back to a
    plain in-process dict with per-key TTL.

The dashboard's queries change slowly, so a short TTL turns a multi-second
load into an instant one. `invalidate()` is called after a contribution so
the next load reflects it.
"""

import logging
import pickle
import threading
import time
from functools import wraps

from app.core.config import settings

log = logging.getLogger("relieftrace.cache")

DEFAULT_TTL = 60.0
_NS = "relieftrace:cache:"

_mem: dict[str, tuple[float, object]] = {}  # key -> (expires_at_monotonic, value)
_lock = threading.Lock()

_redis = None
_redis_label = "in-process dict"
if settings.redis_url:
    try:
        import redis as _redis_lib

        _redis = _redis_lib.from_url(
            settings.redis_url, socket_connect_timeout=0.5, socket_timeout=0.5
        )
        _redis.ping()
        _redis_label = f"Redis ({settings.redis_url})"
    except Exception as exc:  # noqa: BLE001 - any failure -> fall back
        log.warning("REDIS_URL set but unreachable (%s); using in-process cache", exc)
        _redis = None

log.info("cache backend = %s", _redis_label)

_MISS = object()


def _get(key: str):
    nk = _NS + key
    if _redis is not None:
        try:
            raw = _redis.get(nk)
            return pickle.loads(raw) if raw is not None else _MISS
        except Exception:
            pass  # fall through to memory
    with _lock:
        hit = _mem.get(key)
        if hit and time.monotonic() < hit[0]:
            return hit[1]
    return _MISS


def _set(key: str, value: object, ttl: float) -> None:
    nk = _NS + key
    if _redis is not None:
        try:
            _redis.setex(nk, int(ttl) + 1, pickle.dumps(value))
            return
        except Exception:
            pass
    with _lock:
        _mem[key] = (time.monotonic() + ttl, value)


def cached(ttl: float = DEFAULT_TTL):
    def decorator(fn):
        base = fn.__qualname__

        @wraps(fn)
        def wrapper(*args, **kwargs):
            # ignore a leading FastAPI Request arg; key on the rest
            parts = [repr(a) for a in args if type(a).__name__ != "Request"]
            parts += [f"{k}={v!r}" for k, v in sorted(kwargs.items())]
            key = f"{base}({','.join(parts)})"

            cached_value = _get(key)
            if cached_value is not _MISS:
                return cached_value

            value = fn(*args, **kwargs)
            _set(key, value, ttl)
            return value

        wrapper.cache_base = base
        return wrapper

    return decorator


def invalidate(*prefixes: str) -> None:
    """Drop cached entries whose key starts with any given function qualname.
    No args = clear everything."""
    if _redis is not None:
        try:
            patterns = [f"{_NS}{p}*" for p in prefixes] or [f"{_NS}*"]
            for pat in patterns:
                keys = list(_redis.scan_iter(match=pat, count=200))
                if keys:
                    _redis.delete(*keys)
        except Exception:
            pass
    with _lock:
        if not prefixes:
            _mem.clear()
        else:
            for k in [k for k in _mem if k.startswith(tuple(prefixes))]:
                _mem.pop(k, None)
