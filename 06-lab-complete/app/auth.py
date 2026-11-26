"""
API Key authentication (tiêu chí 6).

  • Client gửi header  X-API-Key: <key>
  • Key phải trùng biến môi trường AGENT_API_KEY
  • Thiếu hoặc sai key → HTTP 401 (không phải 403 hay 422)
"""
import hashlib
import hmac

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from app.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

_UNAUTHORIZED = {"WWW-Authenticate": "ApiKey"}


def verify_api_key(api_key: str | None = Security(api_key_header)) -> str:
    """Dependency cho FastAPI — dùng trong /ask: Depends(verify_api_key)."""
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="Missing API key. Send header: X-API-Key: <key>",
            headers=_UNAUTHORIZED,
        )
    # So sánh hằng-thời-gian để không lộ key qua timing attack
    if not hmac.compare_digest(api_key.encode(), settings.agent_api_key.encode()):
        raise HTTPException(status_code=401, detail="Invalid API key.", headers=_UNAUTHORIZED)
    return api_key


def key_id(api_key: str) -> str:
    """ID ổn định của một API key để làm key Redis / log — không bao giờ lưu key gốc."""
    return hashlib.sha256(api_key.encode()).hexdigest()[:16]
