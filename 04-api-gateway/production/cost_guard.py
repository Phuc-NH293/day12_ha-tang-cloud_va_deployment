import logging
import os
import time
from dataclasses import dataclass

from fastapi import HTTPException

try:
    import redis
except ImportError:
    redis = None


logger = logging.getLogger(__name__)

PRICE_PER_1K_INPUT_TOKENS = 0.00015
PRICE_PER_1K_OUTPUT_TOKENS = 0.0006


@dataclass
class UsageRecord:
    user_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    request_count: int = 0
    month: str = ""

    @property
    def total_cost_usd(self) -> float:
        input_cost = (self.input_tokens / 1000) * PRICE_PER_1K_INPUT_TOKENS
        output_cost = (self.output_tokens / 1000) * PRICE_PER_1K_OUTPUT_TOKENS
        return round(input_cost + output_cost, 6)


class CostGuard:
    def __init__(
        self,
        monthly_budget_usd: float = 10.0,
        global_monthly_budget_usd: float = 100.0,
        warn_at_pct: float = 0.8,
        redis_url: str | None = None,
    ):
        self.monthly_budget_usd = monthly_budget_usd
        self.global_monthly_budget_usd = global_monthly_budget_usd
        self.warn_at_pct = warn_at_pct

        # Compatibility for app.py admin_stats.
        self.daily_budget_usd = monthly_budget_usd
        self.global_daily_budget_usd = global_monthly_budget_usd
        self._global_cost = 0.0

        self._records: dict[str, UsageRecord] = {}
        self._redis = self._connect_redis(redis_url or os.getenv("REDIS_URL", ""))

    def _connect_redis(self, redis_url: str):
        if not redis or not redis_url:
            return None
        try:
            client = redis.from_url(redis_url, decode_responses=True)
            client.ping()
            return client
        except redis.RedisError as exc:
            logger.warning("Redis unavailable for cost guard, using memory fallback: %s", exc)
            return None

    def _month(self) -> str:
        return time.strftime("%Y-%m")

    def _user_key(self, user_id: str) -> str:
        return f"budget:{user_id}:{self._month()}"

    def _global_key(self) -> str:
        return f"budget:global:{self._month()}"

    def _record_from_redis(self, user_id: str) -> UsageRecord:
        data = self._redis.hgetall(self._user_key(user_id))
        return UsageRecord(
            user_id=user_id,
            input_tokens=int(data.get("input_tokens", 0)),
            output_tokens=int(data.get("output_tokens", 0)),
            request_count=int(data.get("request_count", 0)),
            month=self._month(),
        )

    def _get_record(self, user_id: str) -> UsageRecord:
        if self._redis:
            return self._record_from_redis(user_id)

        month = self._month()
        record = self._records.get(user_id)
        if not record or record.month != month:
            self._records[user_id] = UsageRecord(user_id=user_id, month=month)
        return self._records[user_id]

    def check_budget(self, user_id: str) -> None:
        record = self._get_record(user_id)
        global_cost = self._get_global_cost()

        if global_cost >= self.global_monthly_budget_usd:
            logger.critical("GLOBAL BUDGET EXCEEDED: $%.4f", global_cost)
            raise HTTPException(
                status_code=503,
                detail="Service temporarily unavailable due to budget limits. Try again next month.",
            )

        if record.total_cost_usd >= self.monthly_budget_usd:
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "Monthly budget exceeded",
                    "used_usd": record.total_cost_usd,
                    "budget_usd": self.monthly_budget_usd,
                    "resets_at": "start of next month",
                },
            )

        if record.total_cost_usd >= self.monthly_budget_usd * self.warn_at_pct:
            logger.warning(
                "User %s at %.0f%% monthly budget",
                user_id,
                record.total_cost_usd / self.monthly_budget_usd * 100,
            )

    def record_usage(self, user_id: str, input_tokens: int, output_tokens: int) -> UsageRecord:
        cost = (
            input_tokens / 1000 * PRICE_PER_1K_INPUT_TOKENS
            + output_tokens / 1000 * PRICE_PER_1K_OUTPUT_TOKENS
        )

        if self._redis:
            key = self._user_key(user_id)
            pipe = self._redis.pipeline()
            pipe.hincrby(key, "input_tokens", input_tokens)
            pipe.hincrby(key, "output_tokens", output_tokens)
            pipe.hincrby(key, "request_count", 1)
            pipe.expire(key, 32 * 24 * 3600)
            pipe.incrbyfloat(self._global_key(), cost)
            pipe.expire(self._global_key(), 32 * 24 * 3600)
            pipe.execute()
            record = self._record_from_redis(user_id)
            self._global_cost = self._get_global_cost()
        else:
            record = self._get_record(user_id)
            record.input_tokens += input_tokens
            record.output_tokens += output_tokens
            record.request_count += 1
            self._global_cost += cost

        logger.info(
            "Usage: user=%s req=%s cost=$%.4f/%.2f",
            user_id,
            record.request_count,
            record.total_cost_usd,
            self.monthly_budget_usd,
        )
        return record

    def _get_global_cost(self) -> float:
        if self._redis:
            return float(self._redis.get(self._global_key()) or 0.0)
        return self._global_cost

    def get_usage(self, user_id: str) -> dict:
        record = self._get_record(user_id)
        return {
            "user_id": user_id,
            "month": record.month or self._month(),
            "requests": record.request_count,
            "input_tokens": record.input_tokens,
            "output_tokens": record.output_tokens,
            "cost_usd": record.total_cost_usd,
            "budget_usd": self.monthly_budget_usd,
            "budget_remaining_usd": max(0, self.monthly_budget_usd - record.total_cost_usd),
            "budget_used_pct": round(record.total_cost_usd / self.monthly_budget_usd * 100, 1),
        }


cost_guard = CostGuard(monthly_budget_usd=10.0, global_monthly_budget_usd=100.0)
