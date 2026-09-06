"""
Realtime event fan-out for the live dashboard (SSE).

Design:
  - Every connected SSE client registers an ``asyncio.Queue`` with the
    in-process :data:`broadcaster`.
  - :func:`publish` drops an event onto every local queue *and*, when Redis is
    configured, onto a Redis pub/sub channel so the other FastAPI Cloud
    replicas deliver it to their own connected clients.
  - :func:`redis_relay` runs for the lifetime of the app: it subscribes to that
    same channel and forwards messages from *other* replicas into the local
    broadcaster. Messages this replica published are tagged with an origin id
    and skipped here to avoid double delivery.

With no Redis this still works for a single replica - :func:`publish` reaches
the local queues directly.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

from app.core.config import settings

log = logging.getLogger("relieftrace.events")

_ORIGIN = uuid.uuid4().hex  # this process; lets redis_relay skip its own messages


class Broadcaster:
    """Keeps the set of per-client queues and pushes events to all of them."""

    def __init__(self) -> None:
        self._clients: set[asyncio.Queue[str]] = set()
        self._lock = asyncio.Lock()

    async def register(self) -> asyncio.Queue[str]:
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=64)
        async with self._lock:
            self._clients.add(q)
        return q

    async def unregister(self, q: asyncio.Queue[str]) -> None:
        async with self._lock:
            self._clients.discard(q)

    def fan_out(self, payload: str) -> None:
        for q in list(self._clients):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                # slow client - drop the event for them rather than block others
                log.warning("dropping event for a slow SSE client")

    @property
    def client_count(self) -> int:
        return len(self._clients)


broadcaster = Broadcaster()

_redis = None
if settings.redis_url:
    try:
        import redis.asyncio as _aioredis

        _redis = _aioredis.from_url(settings.redis_url, decode_responses=True)
    except Exception as exc:  # noqa: BLE001
        log.warning("events: redis.asyncio unavailable (%s); single-replica fan-out only", exc)
        _redis = None


async def publish(event: dict) -> None:
    """Broadcast an event to every connected client across all replicas."""
    envelope = {"_origin": _ORIGIN, **event}
    payload = json.dumps(envelope, default=str)

    # local clients first (instant, no network)
    broadcaster.fan_out(json.dumps(event, default=str))

    # other replicas via Redis
    if _redis is not None:
        try:
            await _redis.publish(settings.events_channel, payload)
        except Exception as exc:  # noqa: BLE001
            log.warning("events: redis publish failed: %s", exc)


async def redis_relay() -> None:
    """Lifespan task: forward events from other replicas into the local broadcaster."""
    if _redis is None:
        return
    while True:
        try:
            pubsub = _redis.pubsub()
            await pubsub.subscribe(settings.events_channel)
            log.info("events: subscribed to %s", settings.events_channel)
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                try:
                    envelope = json.loads(message["data"])
                except (ValueError, TypeError):
                    continue
                if envelope.get("_origin") == _ORIGIN:
                    continue  # we already fanned this out locally
                envelope.pop("_origin", None)
                broadcaster.fan_out(json.dumps(envelope, default=str))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - keep the relay alive
            log.warning("events: redis relay error (%s); reconnecting in 2s", exc)
            await asyncio.sleep(2)
