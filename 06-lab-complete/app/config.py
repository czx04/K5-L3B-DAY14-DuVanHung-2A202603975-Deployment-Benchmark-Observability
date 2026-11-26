"""
Config — 12-Factor: mọi cấu hình đọc từ biến môi trường.

  • Biến môi trường thật (shell, Docker, Railway/Render dashboard) luôn được ưu tiên.
  • Khi chạy local có thể đặt trong file .env (đã nằm trong .gitignore) — xem .env.example.
  • Không có secret nào trong code: AGENT_API_KEY bắt buộc phải đến từ môi trường.
"""
import os
from dataclasses import dataclass, field

try:  # .env chỉ để tiện khi chạy local; không ghi đè biến đã có trong môi trường
    from dotenv import load_dotenv

    load_dotenv(override=False)
except ImportError:  # pragma: no cover
    pass


def _int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    return int(raw) if raw else default


def _float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    return float(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    port: int = field(default_factory=lambda: _int("PORT", 8000))
    environment: str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper())

    # Secret — không có giá trị mặc định
    agent_api_key: str = field(default_factory=lambda: os.getenv("AGENT_API_KEY", ""))

    # Redis: dùng chung cho rate limiter + cost guard (state không nằm trong RAM)
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    redis_timeout_seconds: float = field(default_factory=lambda: _float("REDIS_TIMEOUT_SECONDS", 1.0))

    # Rate limit: số request tối đa / 60 giây cho mỗi API key
    rate_limit_per_minute: int = field(default_factory=lambda: _int("RATE_LIMIT_PER_MINUTE", 10))
    rate_limit_window_seconds: int = 60

    # Cost guard: ngân sách theo ngày (UTC) và theo tháng (UTC) cho mỗi API key
    daily_budget_usd: float = field(default_factory=lambda: _float("DAILY_BUDGET_USD", 1.0))
    monthly_budget_usd: float = field(default_factory=lambda: _float("MONTHLY_BUDGET_USD", 10.0))

    def validate(self) -> "Settings":
        """Fail fast: thiếu cấu hình bắt buộc thì không khởi động."""
        if not self.agent_api_key:
            raise RuntimeError(
                "AGENT_API_KEY is not set. Export it (or put it in .env) before starting the agent."
            )
        if self.rate_limit_per_minute < 1:
            raise RuntimeError("RATE_LIMIT_PER_MINUTE must be >= 1")
        if self.daily_budget_usd <= 0 or self.monthly_budget_usd <= 0:
            raise RuntimeError("DAILY_BUDGET_USD and MONTHLY_BUDGET_USD must be > 0")
        return self


settings = Settings().validate()
