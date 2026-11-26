"""
Cost guard (tiêu chí 8).

  • Cộng dồn chi phí LLM (tính theo token) vào Redis, theo ngày UTC và theo tháng UTC.
  • Đã tiêu ≥ DAILY_BUDGET_USD trong ngày hoặc ≥ MONTHLY_BUDGET_USD trong tháng → HTTP 402.
  • Key Redis có ngày/tháng trong tên (cost:<id>:d:2026-11-26, cost:<id>:m:2026-11) nên
    sang ngày / tháng mới tự reset; EXPIRE dọn key cũ.
"""
from datetime import datetime, timezone

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006

_DAY_TTL = 2 * 24 * 3600
_MONTH_TTL = 32 * 24 * 3600


def _keys(identity: str) -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    return f"cost:{identity}:d:{now:%Y-%m-%d}", f"cost:{identity}:m:{now:%Y-%m}"


def estimate_tokens(text: str) -> int:
    """Ước lượng token cho mock LLM (≈ 2 token / từ)."""
    return max(1, len(text.split()) * 2)


def request_cost(input_tokens: int, output_tokens: int) -> float:
    return input_tokens / 1000 * PRICE_INPUT_PER_1K + output_tokens / 1000 * PRICE_OUTPUT_PER_1K


def get_spent(identity: str) -> dict:
    day_key, month_key = _keys(identity)
    day, month = r.mget(day_key, month_key)
    return {"daily_usd": float(day or 0), "monthly_usd": float(month or 0)}


def check_budget(identity: str) -> dict:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    spent = get_spent(identity)
    if spent["daily_usd"] >= settings.daily_budget_usd:
        period, used, budget, resets = "daily", spent["daily_usd"], settings.daily_budget_usd, "00:00 UTC"
    elif spent["monthly_usd"] >= settings.monthly_budget_usd:
        period, used, budget, resets = "monthly", spent["monthly_usd"], settings.monthly_budget_usd, "1st of month UTC"
    else:
        return spent
    raise HTTPException(
        status_code=402,
        detail={
            "error": f"{period.capitalize()} budget exceeded",
            "used_usd": round(used, 6),
            "budget_usd": budget,
            "resets_at": resets,
        },
    )


def record_cost(identity: str, input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng, trả về chi phí request."""
    cost = request_cost(input_tokens, output_tokens)
    day_key, month_key = _keys(identity)
    pipe = r.pipeline(transaction=True)
    pipe.incrbyfloat(day_key, cost)
    pipe.expire(day_key, _DAY_TTL)
    pipe.incrbyfloat(month_key, cost)
    pipe.expire(month_key, _MONTH_TTL)
    pipe.execute()
    return cost
