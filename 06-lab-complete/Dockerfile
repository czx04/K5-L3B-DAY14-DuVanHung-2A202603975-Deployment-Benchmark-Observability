# ============================================================
# Production Dockerfile — Part 6 agent
#   • Multi-stage: builder cài dependencies vào virtualenv, runtime chỉ copy venv + code
#   • Base python:3.11-slim, chạy bằng user non-root `agent`
#   • HEALTHCHECK gọi GET /health
#   • Lắng nghe theo $PORT (Railway/Render cấp), mặc định 8000
#   • `exec` → uvicorn là PID 1, nhận SIGTERM trực tiếp khi `docker stop`
# Build:  docker build -t day14-agent .
# Run:    docker run -p 8000:8000 -e AGENT_API_KEY=... -e REDIS_URL=redis://host:6379/0 day14-agent
# ============================================================

# ── Stage 1: builder ─────────────────────────────────────────
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy requirements trước để tận dụng layer cache khi chỉ sửa code
COPY requirements.txt .
RUN pip install -r requirements.txt


# ── Stage 2: runtime ─────────────────────────────────────────
FROM python:3.11-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    WEB_CONCURRENCY=2 \
    ENVIRONMENT=production

RUN groupadd --system agent && useradd --system --gid agent --no-create-home agent

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=agent:agent app/ ./app/
COPY --chown=agent:agent utils/ ./utils/

USER agent

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health', timeout=4)" || exit 1

# Shell form chỉ để đọc ${PORT}; `exec` thay thế shell → uvicorn là PID 1
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-2} --timeout-graceful-shutdown 8 --no-server-header"]
