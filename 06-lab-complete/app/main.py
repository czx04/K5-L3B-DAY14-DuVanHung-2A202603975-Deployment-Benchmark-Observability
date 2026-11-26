"""
Production AI Agent — Part 6 Final Project.

Luồng xử lý POST /ask:
    X-API-Key (401) → rate limit trong Redis (429) → budget trong Redis (402)
    → gọi LLM (mock) → ghi chi phí vào Redis → 200

Chạy:
    AGENT_API_KEY=dev-key uvicorn app.main:app --workers 2
Kiểm tra:
    python check_production_ready.py
"""
import json
import logging
import signal
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import redis
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from app import cost_guard, redis_client
from app.auth import key_id, verify_api_key
from app.config import settings
from app.rate_limiter import check_rate_limit
from utils.mock_llm import ask as llm_ask

APP_VERSION = "1.0.0"
START_TIME = time.time()


# ──────────────────────────────────────────────────────────
# Structured logging — mỗi dòng log của app là 1 JSON object
# ──────────────────────────────────────────────────────────
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "lvl": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        entry.update(getattr(record, "fields", {}) or {})
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


def _build_logger() -> logging.Logger:
    log = logging.getLogger("agent")
    log.setLevel(settings.log_level)
    log.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    log.addHandler(handler)
    log.propagate = False  # không để root logger in lại dạng text
    return log


logger = _build_logger()


def log(event: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, event, extra={"fields": fields})


# ──────────────────────────────────────────────────────────
# Graceful shutdown
# ──────────────────────────────────────────────────────────
_draining = False  # True từ lúc nhận SIGTERM → /ready trả 503 để LB ngừng gửi traffic mới


def _install_drain_handler() -> None:
    """
    Gọi trong lifespan startup — lúc này uvicorn ĐÃ cài handler SIGTERM của nó
    (uvicorn import app bên trong capture_signals()). Vì vậy KHÔNG được gọi signal.signal
    lúc import module: làm vậy sẽ đè mất handler của uvicorn và process không bao giờ tắt.
    Ở đây ta xâu chuỗi: đánh dấu draining rồi trả quyền cho handler cũ của uvicorn.
    """
    try:
        previous = signal.getsignal(signal.SIGTERM)
    except ValueError:
        return

    def _on_sigterm(signum, frame):
        global _draining
        _draining = True
        log("sigterm_received", action="draining: stop accepting, finish in-flight requests")
        if callable(previous):
            previous(signum, frame)  # trả quyền cho uvicorn: đóng socket, chờ request đang chạy

    try:
        signal.signal(signal.SIGTERM, _on_sigterm)
    except ValueError:  # không ở main thread (vd chạy trong test client)
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    _install_drain_handler()
    log("startup", version=APP_VERSION, environment=settings.environment,
        rate_limit_per_minute=settings.rate_limit_per_minute,
        daily_budget_usd=settings.daily_budget_usd, monthly_budget_usd=settings.monthly_budget_usd,
        redis_ok=redis_client.redis_healthy())
    yield
    # uvicorn đã đóng socket và chờ các request đang chạy xong trước khi tới đây
    log("shutdown", uptime_seconds=round(time.time() - START_TIME, 1))
    redis_client.close()
    log("shutdown_complete")


app = FastAPI(title="Production AI Agent", version=APP_VERSION, lifespan=lifespan,
              docs_url=None if settings.environment == "production" else "/docs",
              redoc_url=None, openapi_url=None if settings.environment == "production" else "/openapi.json")


# ──────────────────────────────────────────────────────────
# Middleware: request id + access log JSON + security headers
# ──────────────────────────────────────────────────────────
@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    request.state.request_id = request_id
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:  # lỗi chưa được bắt ở đâu khác — không lộ stack trace cho client
        log("unhandled_error", logging.ERROR, request_id=request_id, path=request.url.path, exc_info=True)
        response = JSONResponse(status_code=500,
                                content={"error": "internal_error", "request_id": request_id})
    ms = round((time.perf_counter() - started) * 1000, 1)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    if request.url.path not in ("/health", "/ready"):
        log("request", method=request.method, path=request.url.path,
            status=response.status_code, ms=ms, request_id=request_id)
    return response


# ──────────────────────────────────────────────────────────
# Error handlers — mã lỗi rõ ràng, body gọn, không stack trace
# ──────────────────────────────────────────────────────────
@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    details = []
    for e in exc.errors():
        field = "body" if e.get("type") == "json_invalid" else \
            ".".join(str(p) for p in e.get("loc", [])[1:]) or "body"
        details.append({"field": field, "msg": e.get("msg")})
    return JSONResponse(status_code=422, content={"error": "invalid_request", "details": details})


@app.exception_handler(redis.RedisError)
async def redis_unavailable(request: Request, exc: redis.RedisError):
    log("dependency_unavailable", logging.WARNING, dependency="redis", error=type(exc).__name__,
        path=request.url.path)
    return JSONResponse(status_code=503, headers={"Retry-After": "5"},
                        content={"error": "service_unavailable", "detail": "State store unavailable, retry later."})


# ──────────────────────────────────────────────────────────
# Health checks
# ──────────────────────────────────────────────────────────
@app.get("/health")
def health():
    """Liveness: process còn sống → luôn 200 (không phụ thuộc Redis)."""
    return {
        "status": "ok",
        "version": APP_VERSION,
        "environment": settings.environment,
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/ready")
def ready():
    """Readiness: 200 khi nhận được traffic; 503 khi đang tắt hoặc Redis không kết nối được."""
    if _draining:
        return JSONResponse(status_code=503, content={"ready": False, "reason": "shutting_down"})
    if not redis_client.redis_healthy():
        return JSONResponse(status_code=503, content={"ready": False, "reason": "redis_unavailable"})
    return {"ready": True}


# ──────────────────────────────────────────────────────────
# Agent endpoint
# ──────────────────────────────────────────────────────────
class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = Field(default=None, max_length=128)

    @field_validator("question")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v


@app.post("/ask")
def ask(body: AskRequest, request: Request, api_key: str = Depends(verify_api_key)):
    # `def` (không async): FastAPI chạy trong threadpool → mock LLM blocking không chặn event loop
    question = body.question
    identity = key_id(api_key)

    rate = check_rate_limit(identity)          # 429 khi vượt RATE_LIMIT_PER_MINUTE
    cost_guard.check_budget(identity)          # 402 khi hết DAILY/MONTHLY budget

    started = time.perf_counter()
    answer = llm_ask(question)
    llm_ms = round((time.perf_counter() - started) * 1000, 1)

    input_tokens = cost_guard.estimate_tokens(question)
    output_tokens = cost_guard.estimate_tokens(answer)
    cost = cost_guard.record_cost(identity, input_tokens, output_tokens)
    spent = cost_guard.get_spent(identity)

    log("llm_call", request_id=request.state.request_id, key_id=identity, user_id=body.user_id,
        question_chars=len(question), input_tokens=input_tokens, output_tokens=output_tokens,
        cost_usd=round(cost, 8), llm_ms=llm_ms)

    return {
        "question": question,
        "answer": answer,
        "model": "mock-llm",
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost, 8),
            "rate_limit_remaining": rate["remaining"],
            "daily_spent_usd": round(spent["daily_usd"], 6),
            "daily_budget_remaining_usd": round(max(0.0, settings.daily_budget_usd - spent["daily_usd"]), 6),
        },
    }
