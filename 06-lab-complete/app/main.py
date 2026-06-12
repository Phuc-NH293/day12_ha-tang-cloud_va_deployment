import json
import logging
import os
import signal
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, estimate_cost, get_budget_usage, record_usage
from app.llm import ask as llm_ask
from app.rate_limiter import check_rate_limit
from app.storage import get_redis, storage_status


logging.basicConfig(
    level=logging.DEBUG if settings.debug else getattr(logging, settings.log_level.upper()),
    format="%(message)s",
)
logger = logging.getLogger(__name__)

START_TIME = time.time()
INSTANCE_ID = os.getenv("INSTANCE_ID", f"agent-{uuid.uuid4().hex[:8]}")
_is_ready = False
_request_count = 0
_error_count = 0
_in_flight_requests = 0


def log_event(event: str, **fields):
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "level": "info",
        "event": event,
        "instance": INSTANCE_ID,
        **fields,
    }
    logger.info(json.dumps(payload, separators=(",", ":")))


def _history_key(user_id: str) -> str:
    return f"history:{user_id}"


def load_history(user_id: str) -> list[dict]:
    redis_client = get_redis()
    key = _history_key(user_id)
    if redis_client:
        items = redis_client.lrange(key, 0, -1)
        return [json.loads(item) for item in items]
    return settings.memory_store.setdefault(key, [])


def append_history(user_id: str, role: str, content: str) -> list[dict]:
    message = {
        "role": role,
        "content": content,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    redis_client = get_redis()
    key = _history_key(user_id)
    if redis_client:
        redis_client.rpush(key, json.dumps(message, separators=(",", ":")))
        redis_client.ltrim(key, -settings.max_history_messages, -1)
        redis_client.expire(key, settings.session_ttl_seconds)
        return load_history(user_id)

    history = settings.memory_store.setdefault(key, [])
    history.append(message)
    del history[:-settings.max_history_messages]
    return history


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = Field(default=None, min_length=1, max_length=120)


class AskResponse(BaseModel):
    user_id: str
    question: str
    answer: str
    model: str
    history_length: int
    served_by: str
    timestamp: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _is_ready
    log_event(
        "startup",
        app=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        storage=storage_status()["mode"],
    )
    _is_ready = True
    log_event("ready")
    yield
    _is_ready = False
    log_event("shutdown")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)


@app.middleware("http")
async def request_middleware(request: Request, call_next):
    global _request_count, _error_count, _in_flight_requests
    start = time.time()
    _request_count += 1
    _in_flight_requests += 1
    try:
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        if "server" in response.headers:
            del response.headers["server"]
        log_event(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            ms=round((time.time() - start) * 1000, 1),
        )
        return response
    except Exception:
        _error_count += 1
        raise
    finally:
        _in_flight_requests -= 1


@app.get("/", tags=["Info"])
def root():
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "instance": INSTANCE_ID,
        "endpoints": {
            "ask": "POST /ask (requires X-API-Key)",
            "history": "GET /history/{user_id} (requires X-API-Key)",
            "health": "GET /health",
            "ready": "GET /ready",
            "metrics": "GET /metrics (requires X-API-Key)",
        },
    }


@app.post("/ask", response_model=AskResponse, tags=["Agent"])
async def ask_agent(
    body: AskRequest,
    request: Request,
    api_key: str = Depends(verify_api_key),
):
    user_id = body.user_id or f"key-{api_key[:8]}"
    check_rate_limit(user_id)

    input_tokens = max(1, len(body.question.split()) * 2)
    check_budget(user_id, estimated_cost=estimate_cost(input_tokens, 0))

    history_before = append_history(user_id, "user", body.question)
    answer = llm_ask(body.question, history_before)
    output_tokens = max(1, len(answer.split()) * 2)
    usage = record_usage(user_id, input_tokens, output_tokens)
    history_after = append_history(user_id, "assistant", answer)

    log_event(
        "agent_call",
        user_id=user_id,
        client=str(request.client.host) if request.client else "unknown",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=usage["monthly_spend_usd"],
    )

    return AskResponse(
        user_id=user_id,
        question=body.question,
        answer=answer,
        model=settings.llm_model,
        history_length=len(history_after),
        served_by=INSTANCE_ID,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.get("/history/{user_id}", tags=["Agent"])
def history(user_id: str, _api_key: str = Depends(verify_api_key)):
    messages = load_history(user_id)
    return {"user_id": user_id, "messages": messages, "count": len(messages)}


@app.delete("/history/{user_id}", tags=["Agent"])
def delete_history(user_id: str, _api_key: str = Depends(verify_api_key)):
    redis_client = get_redis()
    key = _history_key(user_id)
    if redis_client:
        redis_client.delete(key)
    else:
        settings.memory_store.pop(key, None)
    return {"deleted": user_id}


@app.get("/health", tags=["Operations"])
def health():
    return {
        "status": "ok",
        "version": settings.app_version,
        "environment": settings.environment,
        "instance": INSTANCE_ID,
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "total_requests": _request_count,
        "in_flight_requests": _in_flight_requests,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/ready", tags=["Operations"])
def ready():
    if not _is_ready:
        raise HTTPException(status_code=503, detail="Application is not ready")

    storage = storage_status()
    if settings.require_redis and not storage["redis_connected"]:
        raise HTTPException(status_code=503, detail="Redis is not ready")

    return {"ready": True, "storage": storage, "instance": INSTANCE_ID}


@app.get("/metrics", tags=["Operations"])
def metrics(api_key: str = Depends(verify_api_key)):
    user_id = f"key-{api_key[:8]}"
    budget = get_budget_usage(user_id)
    return {
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "total_requests": _request_count,
        "error_count": _error_count,
        "in_flight_requests": _in_flight_requests,
        "budget": budget,
        "storage": storage_status(),
    }


def _handle_signal(signum, _frame):
    log_event("signal", signum=signum, in_flight_requests=_in_flight_requests)


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


if __name__ == "__main__":
    log_event("serve", host=settings.host, port=settings.port)
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        timeout_graceful_shutdown=30,
    )
