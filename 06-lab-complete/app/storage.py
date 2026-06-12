from __future__ import annotations

import redis

from app.config import settings


_client = None
_last_failure = 0.0


def get_redis():
    global _client, _last_failure
    if not settings.redis_url:
        return None
    if _last_failure and settings.require_redis is False:
        import time

        if time.time() - _last_failure < 2:
            return None
    if _client:
        try:
            _client.ping()
            return _client
        except redis.RedisError:
            _client = None
    try:
        client = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=0.2,
            socket_timeout=0.2,
        )
        client.ping()
        _client = client
        return client
    except redis.RedisError:
        import time

        _last_failure = time.time()
        return None


def storage_status() -> dict:
    client = get_redis()
    if client:
        return {"mode": "redis", "redis_connected": True}
    return {"mode": "memory-fallback", "redis_connected": False}
