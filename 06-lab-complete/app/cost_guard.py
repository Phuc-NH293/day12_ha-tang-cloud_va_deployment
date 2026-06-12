import time

from fastapi import HTTPException

from app.config import settings
from app.storage import get_redis


PRICE_PER_1K_INPUT_TOKENS = 0.00015
PRICE_PER_1K_OUTPUT_TOKENS = 0.0006


def current_month() -> str:
    return time.strftime("%Y-%m")


def estimate_cost(input_tokens: int, output_tokens: int) -> float:
    input_cost = (input_tokens / 1000) * PRICE_PER_1K_INPUT_TOKENS
    output_cost = (output_tokens / 1000) * PRICE_PER_1K_OUTPUT_TOKENS
    return round(input_cost + output_cost, 8)


def _budget_key(user_id: str) -> str:
    return f"budget:{user_id}:{current_month()}"


def _memory_spend(key: str) -> float:
    return float(settings.memory_store.get(key, 0.0))


def get_budget_usage(user_id: str) -> dict:
    key = _budget_key(user_id)
    redis_client = get_redis()
    spent = float(redis_client.get(key) or 0.0) if redis_client else _memory_spend(key)
    return {
        "user_id": user_id,
        "month": current_month(),
        "monthly_spend_usd": round(spent, 6),
        "monthly_budget_usd": settings.monthly_budget_usd,
        "remaining_usd": round(max(0.0, settings.monthly_budget_usd - spent), 6),
    }


def check_budget(user_id: str, estimated_cost: float = 0.0) -> None:
    usage = get_budget_usage(user_id)
    if usage["monthly_spend_usd"] + estimated_cost > settings.monthly_budget_usd:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "Monthly budget exceeded",
                "used_usd": usage["monthly_spend_usd"],
                "budget_usd": settings.monthly_budget_usd,
                "month": usage["month"],
            },
        )


def record_usage(user_id: str, input_tokens: int, output_tokens: int) -> dict:
    cost = estimate_cost(input_tokens, output_tokens)
    check_budget(user_id, cost)
    key = _budget_key(user_id)
    redis_client = get_redis()
    if redis_client:
        spent = redis_client.incrbyfloat(key, cost)
        redis_client.expire(key, 32 * 24 * 3600)
    else:
        spent = _memory_spend(key) + cost
        settings.memory_store[key] = spent
    usage = get_budget_usage(user_id)
    usage["last_request_cost_usd"] = cost
    usage["monthly_spend_usd"] = round(float(spent), 6)
    return usage
