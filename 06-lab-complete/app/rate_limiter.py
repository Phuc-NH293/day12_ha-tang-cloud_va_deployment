import time

from fastapi import HTTPException

from app.config import settings
from app.storage import get_redis


def _memory_bucket(user_id: str) -> list[float]:
    return settings.memory_store.setdefault(f"rate:{user_id}", [])


def check_rate_limit(user_id: str) -> None:
    now = time.time()
    window_start = now - settings.rate_limit_window_seconds
    limit = settings.rate_limit_per_minute
    key = f"rate:{user_id}"
    redis_client = get_redis()

    if redis_client:
        redis_client.zremrangebyscore(key, 0, window_start)
        count = redis_client.zcard(key)
        if count >= limit:
            retry_after = settings.rate_limit_window_seconds
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: {limit} requests per minute",
                headers={"Retry-After": str(retry_after)},
            )
        pipe = redis_client.pipeline()
        pipe.zadd(key, {str(now): now})
        pipe.expire(key, settings.rate_limit_window_seconds * 2)
        pipe.execute()
        return

    bucket = _memory_bucket(user_id)
    bucket[:] = [stamp for stamp in bucket if stamp >= window_start]
    if len(bucket) >= limit:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: {limit} requests per minute",
            headers={"Retry-After": str(settings.rate_limit_window_seconds)},
        )
    bucket.append(now)
