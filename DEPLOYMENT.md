# Deployment Information

## Public URL

**https://day14-agent-af0r.onrender.com**

## Platform

**Render**, deploy theo Blueprint `06-lab-complete/render.yaml` (Infrastructure as Code):

| Resource | Loại | Cấu hình |
|---|---|---|
| `day14-agent` | Web Service, `runtime: docker` | `rootDir: 06-lab-complete`, build từ `Dockerfile` (multi-stage, `python:3.11-slim`, user non-root), plan free, region Singapore, `healthCheckPath: /health`, `autoDeploy: true` |
| `day14-redis` | Key Value (tương thích Redis) | plan free, region Singapore, `ipAllowList: []` (chỉ nhận kết nối trong mạng nội bộ Render), `maxmemoryPolicy: noeviction` |

- Repo: `czx04/K5-L3B-DAY14-DuVanHung-2A202603975-Deployment-Benchmark-Observability`, nhánh `main`. Blueprint Path: `06-lab-complete/render.yaml`.
- Mỗi lần push lên `main`, Render tự build lại và deploy.
- Log khởi động trên Render:

  ```text
  {"ts": "2026-11-26T08:03:43.339+00:00", "lvl": "INFO", "logger": "agent", "event": "startup", "version": "1.0.0", "environment": "production", "rate_limit_per_minute": 10, "daily_budget_usd": 1.0, "monthly_budget_usd": 10.0, "redis_ok": true}
  INFO:     Uvicorn running on http://0.0.0.0:10000 (Press CTRL+C to quit)
  ==> Your service is live 🎉
  ```

  App lắng nghe trên cổng `10000` mà Render cấp qua biến `$PORT` (CMD trong Dockerfile dùng `${PORT:-8000}`), và kết nối Redis thành công (`redis_ok: true`).

## Test Commands

Đặt biến môi trường trước khi chạy. Key được nhập ẩn, không ghi vào file và không lưu vào lịch sử shell:

```bash
export BASE=https://day14-agent-af0r.onrender.com
read -s AGENT_API_KEY && export AGENT_API_KEY
```

Bốn lệnh tự kiểm tra (CP6). Mỗi lệnh chỉ in mã HTTP:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```

Kết quả chạy 4 lệnh (key thật nhập ẩn bằng `read -s`), 2026-11-26: **`200 200 401 200`**, xem [screenshots/test.png](screenshots/test.png).

### Health check

```bash
curl https://day14-agent-af0r.onrender.com/health
```

```json
{"status":"ok","version":"1.0.0","environment":"production","uptime_seconds":21.5,"timestamp":"2026-11-26T08:04:04.690744+00:00"}
```

### Readiness (kiểm tra kết nối Redis)

```bash
curl https://day14-agent-af0r.onrender.com/ready
```

```json
{"ready":true}
```

### API test (có xác thực)

```bash
curl -X POST https://day14-agent-af0r.onrender.com/ask \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Hello"}'
```

### Kết quả kiểm tra từ máy local (không dùng key), lúc 2026-11-26 08:04 UTC

| Request | HTTP |
|---|---|
| `GET /health` | 200 |
| `GET /ready` | 200 (`{"ready":true}`) |
| `POST /ask` không có `X-API-Key` | 401 |
| `POST /ask` với key sai | 401 |
| `GET /ask` (sai method) | 405 |
| `GET /docs` | 404 (Swagger bị tắt khi `ENVIRONMENT=production`) |

Chạy script chấm với tham số `--public-url`:

```text
$ python check_production_ready.py --public-url https://day14-agent-af0r.onrender.com
     ✅ Public URL: GET https://day14-agent-af0r.onrender.com/health → 200
```

Rate limit (10 request/phút cho mỗi key, state lưu trong Render Key Value): gửi request thứ 11 trong vòng 60 giây sẽ nhận **429** kèm header `Retry-After`.

> Gói free của Render cho service ngủ sau khoảng 15 phút không có traffic. Request đầu tiên sau đó mất khoảng 30–50 giây để service khởi động lại (cold start).

## Environment Variables Set

Các biến được đặt trên Render (Blueprint hoặc Dashboard), **không có trong code hay trong git**:

| Biến | Nguồn | Giá trị |
|---|---|---|
| `AGENT_API_KEY` | Dashboard (`sync: false`) | secret ngẫu nhiên, chỉ đặt trên Render |
| `REDIS_URL` | `fromService: keyvalue day14-redis → connectionString` | do Render tự sinh (mạng nội bộ) |
| `PORT` | Render tự cấp | `10000` |
| `ENVIRONMENT` | `render.yaml` | `production` |
| `RATE_LIMIT_PER_MINUTE` | `render.yaml` | `10` |
| `DAILY_BUDGET_USD` | `render.yaml` | `1` |
| `MONTHLY_BUDGET_USD` | `render.yaml` | `10` |
| `WEB_CONCURRENCY` | `render.yaml` | `1` (gói free chỉ có 0.1 CPU và 512 MB RAM) |

Lần deploy đầu bị lỗi vì chưa đặt `AGENT_API_KEY`. App được viết để **dừng ngay khi thiếu cấu hình bắt buộc** (`RuntimeError: AGENT_API_KEY is not set`), thay vì chạy mà không có xác thực. Đặt biến này trên Dashboard rồi deploy lại thì app chạy bình thường.

## Screenshots

- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
