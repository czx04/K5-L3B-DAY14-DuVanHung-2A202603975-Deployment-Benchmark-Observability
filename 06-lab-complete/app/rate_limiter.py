"""
Rate limiting (tiêu chí 7).

  • Mỗi API key tối đa RATE_LIMIT_PER_MINUTE request trong 60 giây — sliding window log.
  • Vượt giới hạn → HTTP 429 kèm header Retry-After.
  • State nằm trong Redis (sorted set, score = timestamp ms) nên mọi worker / instance
    dùng chung và vẫn còn sau khi restart agent.
  • Toàn bộ "dọn cửa sổ → đếm → thêm" chạy trong MỘT script Lua (atomic): nhiều worker
    gọi cùng lúc cũng không lọt quá giới hạn.
"""
import time
import uuid

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

# KEYS[1] = key sorted set; ARGV = now_ms, window_ms, limit, member
_SLIDING_WINDOW = r.register_script("""
local now    = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit  = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)
local count = redis.call('ZCARD', KEYS[1])
if count >= limit then
  local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
  local retry_ms = window
  if oldest[2] then retry_ms = window - (now - tonumber(oldest[2])) end
  return {0, count, retry_ms}
end
redis.call('ZADD', KEYS[1], now, ARGV[4])
redis.call('PEXPIRE', KEYS[1], window)
return {1, count + 1, 0}
""")


def check_rate_limit(key: str) -> dict:
    """
    key: định danh người gọi (hash của API key — không truyền key gốc).
    Trả về {"limit", "remaining"}; vượt giới hạn → HTTPException 429.
    """
    limit = settings.rate_limit_per_minute
    window_ms = settings.rate_limit_window_seconds * 1000
    now_ms = int(time.time() * 1000)
    allowed, count, retry_ms = _SLIDING_WINDOW(
        keys=[f"ratelimit:{key}"],
        args=[now_ms, window_ms, limit, f"{now_ms}-{uuid.uuid4().hex}"],
    )
    if not allowed:
        retry_after = max(1, -(-int(retry_ms) // 1000))  # làm tròn lên, tối thiểu 1 giây
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Rate limit exceeded",
                "limit": limit,
                "window_seconds": settings.rate_limit_window_seconds,
                "retry_after_seconds": retry_after,
            },
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": "0",
            },
        )
    return {"limit": limit, "remaining": max(0, limit - int(count))}
