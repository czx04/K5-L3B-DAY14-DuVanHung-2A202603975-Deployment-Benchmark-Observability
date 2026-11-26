# Day 14 Lab - Mission Answers

## Part 1: Localhost vs Production

Môi trường chạy: macOS, Python 3.12.6, virtualenv `.venv` ở gốc repo, cài `fastapi==0.115.0`, `uvicorn[standard]==0.30.0`, `python-dotenv==1.0.1`.

### Exercise 1.1: Anti-patterns found

File: `01-localhost-vs-production/develop/app.py`

| # | Anti-pattern | Dòng | Hậu quả |
|---|---|---|---|
| 1 | **Hardcode secret**: `OPENAI_API_KEY = "sk-..."` và `DATABASE_URL` chứa user/mật khẩu DB | 17–18 | Push lên GitHub là lộ key và mật khẩu ngay. Key vẫn nằm trong lịch sử git kể cả khi đã xoá file, nên phải revoke. |
| 2 | **Ghi secret ra log**: `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` | 34 | Ai đọc được log (hệ thống log, bạn cùng team, dịch vụ bên thứ ba) cũng thấy key. Khi chạy thử, terminal in đúng dòng `[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this`. |
| 3 | **Config cứng trong code**: `DEBUG = True`, `MAX_TOKENS = 500` | 21–22 | Muốn đổi cấu hình giữa dev, staging và prod phải sửa code rồi deploy lại. Vi phạm nguyên tắc 12-Factor "Config in env". |
| 4 | **Dùng `print()` thay cho logging** | 33, 34, 38, 48 | Không có level, timestamp hay cấu trúc, nên không lọc hoặc tìm kiếm được trên log aggregator. Ngoài ra còn ghi toàn bộ câu hỏi và câu trả lời của người dùng ra log. |
| 5 | **Không có health check** (`/health`, `/ready`) | 42–43 | Nền tảng không biết app đã treo để restart, load balancer không biết khi nào nên dừng gửi traffic. Khi chạy thử, `GET /health` trả **404**. |
| 6 | **Bind `host="localhost"`** | 51 | Chỉ nhận kết nối từ chính máy đó. Trong container hoặc trên cloud thì bên ngoài không gọi vào được (cần `0.0.0.0`). |
| 7 | **Port cố định 8000** | 52 | Railway và Render cấp port qua biến `PORT`. Port cứng làm app không nhận được traffic, và không chạy được nhiều instance trên cùng máy. |
| 8 | **`reload=True` lúc chạy thật** | 53 | Tốn thêm một tiến trình theo dõi file, có thể tự khởi động lại giữa chừng. Đây là tính năng chỉ dành cho lúc dev. |
| 9 | **Không xử lý SIGTERM / graceful shutdown** | cả file | Khi nền tảng deploy bản mới hoặc scale xuống, request đang chạy bị cắt ngang và người dùng nhận lỗi. |
| 10 | **Nhận `question` qua query string**, không validate input | 31 | Câu hỏi nằm trên URL nên bị ghi vào access log, lịch sử trình duyệt và log của proxy. Không giới hạn độ dài. |

### Exercise 1.2: Chạy bản develop

```bash
cd 01-localhost-vs-production/develop
pip install -r requirements.txt
python app.py
```

Gọi thử (bản develop nhận `question` qua query string):

```text
$ curl -i -X POST "http://localhost:8000/ask?question=Hello"
HTTP/1.1 200 OK
server: uvicorn
content-type: application/json

{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

Gửi JSON như trong `CODE_LAB.md` thì bị lỗi 422, vì endpoint đọc `question` từ query:

```text
$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 422 Unprocessable Entity

{"detail":[{"type":"missing","loc":["query","question"],"msg":"Field required","input":null}]}
```

Không có health check:

```text
$ curl -i http://localhost:8000/health
HTTP/1.1 404 Not Found

{"detail":"Not Found"}
```

Log trên terminal của server:

```text
INFO:     Will watch for changes in these directories: [...]
INFO:     Uvicorn running on http://localhost:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [96446] using WatchFiles
Starting agent on localhost:8000...
[DEBUG] Got question: Hello
[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this
[DEBUG] Response: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.
```

**Quan sát:** app chạy và trả lời được, nhưng **chưa sẵn sàng cho production**:
- Secret bị in thẳng ra log.
- Chỉ nghe trên `localhost:8000`.
- Có reloader (2 tiến trình: reloader và server).
- Không có `/health`.

Khi chạy thử còn gặp thêm một vấn đề: lúc bật bản production (`0.0.0.0:8000`) trong khi bản develop (`localhost:8000`) chưa tắt, macOS vẫn cho cả hai cùng nghe cổng 8000. Kết quả là `curl localhost:8000` vẫn rơi vào bản develop. Phải tắt hẳn server cũ trước khi bật server mới.

### Exercise 1.3: So sánh với bản production

```bash
cd ../production
cp .env.example .env
pip install -r requirements.txt
python app.py
```

Kết quả test:

```text
$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 200 OK
{"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.","model":"gpt-4o-mini"}

$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{}'
HTTP/1.1 422 Unprocessable Entity
{"detail":"question field is required"}

$ curl -i http://localhost:8000/health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":4.0,"version":"1.0.0","environment":"development","timestamp":"2026-11-26T07:12:36.118224+00:00"}

$ curl -i http://localhost:8000/ready
HTTP/1.1 200 OK
{"ready":true}
```

Gửi SIGTERM cho tiến trình server (`kill -TERM <pid>`) thì app tắt đúng trình tự, không bị kill ngang:

```text
INFO:     Shutting down
INFO:     Waiting for application shutdown.
INFO:     Application shutdown complete.
INFO:     Finished server process [97014]
```

Thử đổi cấu hình bằng biến môi trường mà không sửa code:

```text
$ PORT=8010 ENVIRONMENT=staging APP_NAME="Env Test" python app.py
$ curl http://localhost:8010/
{"app":"Env Test","version":"1.0.0","environment":"staging","status":"running"}
```

#### Bảng so sánh

| Feature | Develop | Production | Tại sao quan trọng? |
|---|---|---|---|
| **Config** | Hardcode trong code (`DEBUG = True`, `MAX_TOKENS = 500`) | Gom vào `config.py`, đọc từ biến môi trường, có giá trị mặc định | Cùng một bản code (cùng một image) chạy được ở dev, staging và prod, chỉ khác env. Đổi cấu hình không cần build lại. |
| **Secrets** | `OPENAI_API_KEY`, mật khẩu DB nằm trong code và bị in ra log | `os.getenv("OPENAI_API_KEY")`, `.env` nằm trong `.gitignore`, log không chứa secret | Secret không vào git nên không bị lộ khi push code. Có thể đổi key mà không đụng tới code. |
| **Fail fast** | Không kiểm tra gì | `validate()` raise lỗi nếu `ENVIRONMENT=production` mà thiếu `AGENT_API_KEY` | Phát hiện thiếu cấu hình ngay lúc khởi động, không đợi tới lúc người dùng gọi mới lỗi. |
| **Host / Port** | `localhost:8000` cố định | `HOST=0.0.0.0`, `PORT` lấy từ env | Container và cloud cần bind `0.0.0.0`, còn port do nền tảng cấp qua `PORT`. |
| **Health check** | Không có (`/health` trả 404) | `/health` (liveness) và `/ready` (readiness, trả 503 khi chưa sẵn sàng) | Liveness giúp nền tảng biết khi nào restart container. Readiness giúp load balancer chỉ gửi traffic vào instance đã sẵn sàng. |
| **Logging** | `print()`, có in secret và nội dung câu hỏi | `logging` với format JSON, chỉ ghi metadata (`question_length`, `client_ip`) | Log JSON dễ parse, lọc và cảnh báo trên Loki hay Datadog. Không ghi secret hay dữ liệu cá nhân của người dùng. |
| **Input** | Query string, không validate | JSON body, trả 422 kèm thông báo rõ khi thiếu `question` | Lỗi trả về dễ hiểu, dữ liệu không nằm trên URL hay trong access log. |
| **Shutdown** | Tắt đột ngột, không có hook | `lifespan`: đặt `is_ready = False`, chờ request đang chạy làm xong rồi mới tắt. Có thêm handler SIGTERM. | Lúc deploy hoặc scale xuống không làm hỏng request đang chạy. `/ready` báo 503 để load balancer ngừng gửi traffic mới. |
| **Reload** | `reload=True` luôn bật | `reload=settings.debug` (mặc định tắt) | Production không có tiến trình theo dõi file thừa, không tự khởi động lại bất ngờ. |
| **CORS** | Không cấu hình | `ALLOWED_ORIGINS` lấy từ env | Chỉ những frontend được phép mới gọi API từ trình duyệt được. |
| **Metrics** | Không có | `/metrics` (uptime, version, env) | Prometheus và hệ thống giám sát có dữ liệu để scrape. |

#### Những điều phát hiện thêm khi chạy thật

Bản production vẫn còn vài lỗ hổng so với những gì nó tuyên bố:

1. **File `.env` thực ra không được nạp.** `requirements.txt` có `python-dotenv`, nhưng `config.py` không gọi `load_dotenv()`.
   - Kiểm chứng: sửa `APP_NAME=From Dotenv` trong `.env` rồi chạy lại, `GET /` vẫn trả `"app":"AI Agent"` (giá trị mặc định).
   - Chỉ biến môi trường của shell mới có tác dụng (ví dụ `APP_NAME="Env Test"` ở trên).
   - Cách sửa: thêm `from dotenv import load_dotenv; load_dotenv()` ở đầu `config.py`.
2. **Log JSON không bao giờ xuất hiện.** Trong log server chỉ thấy dòng của uvicorn. Các sự kiện `startup`, `agent_request`, `agent_response`, `"Agent shutting down gracefully..."` đều không được in ra.
   - Nguyên nhân: `config.py` gọi `logging.warning("OPENAI_API_KEY not set...")` lúc import, **trước** `logging.basicConfig(...)` trong `app.py`.
   - Lần gọi `logging.warning` đầu tiên tự cấu hình root logger với level WARNING và format mặc định, nên `basicConfig` sau đó không còn tác dụng. Log INFO bị lọc mất.
   - Cách sửa: gọi `basicConfig` trước khi import `config`, hoặc dùng `basicConfig(..., force=True)`.
3. **Handler SIGTERM tự viết không chạy.** `uvicorn.run()` cài lại handler SIGTERM của riêng nó, đè lên `signal.signal(...)`.
   - Graceful shutdown thực tế là do uvicorn kích hoạt `lifespan`, không phải do `handle_sigterm`.
   - Dòng `"Received SIGTERM..."` không xuất hiện trong log.
4. **Format log JSON chưa an toàn.** Format là `'{"msg":"%(message)s"}'`, trong khi message lại là một chuỗi `json.dumps(...)`. Dấu `"` bên trong không được escape, nên dòng log tạo ra là JSON không hợp lệ. Nên dùng formatter JSON thật, ví dụ `python-json-logger`.

### Checkpoint 1: Trả lời câu hỏi

- **Vì sao hardcode secret nguy hiểm?**
  - Code được copy, push và fork đi nhiều nơi. Secret trong code sẽ nằm vĩnh viễn trong lịch sử git.
  - Bot quét GitHub public tìm key `sk-...` trong vài phút sau khi push.
  - Lộ key là bị dùng chùa (mất tiền) hoặc truy cập DB trái phép. Xoá file không đủ, phải revoke key.
  - Ngoài ra, mỗi môi trường cần secret khác nhau. Để secret trong code thì không tách được dev và prod.
- **Dùng biến môi trường thế nào?** Đọc bằng `os.getenv("KEY", default)` và gom về một chỗ (`config.py`).
  - Local: đặt qua shell hoặc file `.env` (nằm trong `.gitignore`, chỉ commit `.env.example`).
  - Cloud: đặt trên dashboard của Railway hoặc Render.
- **Vai trò của health check:**
  - `/health` (liveness) trả lời câu hỏi "tiến trình còn sống không". Nếu fail, nền tảng restart container.
  - `/ready` (readiness) trả lời câu hỏi "đã sẵn sàng nhận traffic chưa". Nếu fail, load balancer ngừng gửi request vào nhưng không restart. Dùng khi đang khởi động, đang tắt, hoặc khi phụ thuộc như Redis hay DB đang chết.
- **Graceful shutdown là gì?**
  - Khi nhận SIGTERM (nền tảng muốn tắt container để deploy hoặc scale), app không chết ngay.
  - App ngừng nhận request mới (`/ready` trả 503), làm xong các request đang chạy, đóng kết nối (DB, Redis) rồi mới thoát.
  - Nhờ vậy người dùng không bị lỗi giữa chừng khi deploy.

---

## Part 2: Docker

Môi trường chạy: Docker Engine 27.4.0 (Docker Desktop, macOS), Docker Compose v2.31.0. Mọi lệnh `docker build` đều chạy từ **gốc repo**, vì Dockerfile `COPY` theo đường dẫn tính từ gốc.

### Exercise 2.1: Dockerfile questions

File: `02-docker/develop/Dockerfile`

1. **Base image:** `python:3.11`. Đây là bản Python đầy đủ, chạy trên Debian, có sẵn gcc, header và nhiều công cụ build. Bản này rất nặng: riêng phần base đã chiếm phần lớn trong tổng 1.17 GB của image develop.
2. **Working directory:** `/app`. `WORKDIR /app` tạo thư mục nếu chưa có, và mọi lệnh `COPY`, `RUN`, `CMD` phía sau đều chạy tương đối từ thư mục này. Kiểm tra bằng `docker exec ... pwd` cho ra `/app`.
3. **Vì sao `COPY requirements.txt` trước:**
   - Docker build theo từng layer và cache từng layer. Một layer chỉ bị build lại khi nó hoặc layer trước nó thay đổi.
   - Dependencies ít thay đổi, còn code thì đổi liên tục. Copy `requirements.txt` rồi `pip install` trước, sau đó mới copy code, thì khi chỉ sửa code, layer `pip install` (mất khoảng 41 giây khi build lần đầu) vẫn được dùng lại từ cache.
   - Nếu `COPY . .` trước, mọi lần sửa code đều làm cache của layer sau mất hiệu lực, nên phải cài lại toàn bộ dependencies.
   - Kiểm chứng: build lại `my-agent:advanced` khi không sửa gì thì mọi bước đều `CACHED`, tổng thời gian **2.8 giây** (lần đầu mất **2 phút 19 giây**).
4. **CMD và ENTRYPOINT:**
   - `CMD ["python", "app.py"]` là lệnh **mặc định**, bị ghi đè hoàn toàn khi truyền lệnh vào `docker run <image> <lệnh khác>`. Ví dụ `docker run my-agent:develop python -c "print(1)"`.
   - `ENTRYPOINT` là phần **cố định** của lệnh, chỉ đổi được bằng cờ `--entrypoint`. Khi dùng cả hai, `CMD` trở thành tham số mặc định truyền cho `ENTRYPOINT`.
   - Cả hai đều nên viết dạng exec form (mảng JSON), để tiến trình chạy với PID 1 và nhận được SIGTERM trực tiếp, không bị `/bin/sh` chặn lại.

### Exercise 2.2: Build và run bản develop

```bash
docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
docker run -d --name cp2-develop -p 8000:8000 my-agent:develop
```

Kết quả (app develop nhận `question` qua query string):

```text
$ curl -i -X POST "http://localhost:8000/ask?question=What%20is%20Docker%3F"
HTTP/1.1 200 OK
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}

$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question": "What is Docker?"}'
HTTP/1.1 422 Unprocessable Entity
{"detail":[{"type":"missing","loc":["query","question"],"msg":"Field required","input":null}]}

$ curl -i http://localhost:8000/health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":3.8,"container":true}
```

Kích thước image:

```text
$ docker images my-agent:develop
REPOSITORY   TAG       IMAGE ID       CREATED         SIZE
my-agent     develop   1729f7fd9886   9 seconds ago   1.17GB
```

Debug container bằng `docker exec` và `docker logs`:

```text
$ docker exec cp2-develop sh -c 'whoami; pwd; ls; python --version'
root
/app
__pycache__  app.py  requirements.txt  utils
Python 3.11.18

$ docker logs cp2-develop
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     172.17.0.1:64536 - "POST /ask?question=What%20is%20Docker%3F HTTP/1.1" 200 OK
```

Nhận xét: container **chạy bằng user `root`**. Nếu app bị khai thác lỗ hổng, kẻ tấn công có quyền root bên trong container.

### Exercise 2.3: Multi-stage build

File: `02-docker/production/Dockerfile`

- **Stage 1 (`builder`, `python:3.11-slim`):**
  - Cài công cụ build (`gcc`, `libpq-dev`).
  - Cài dependencies bằng `pip install --user` vào `/root/.local`.
  - Stage này chỉ dùng để build, không được deploy. Mình build thử riêng stage này (`--target builder`) thì được **404.8 MB**.
- **Stage 2 (`runtime`, `python:3.11-slim`):**
  - Bắt đầu lại từ một image slim sạch.
  - Chỉ `COPY --from=builder /root/.local` (38.2 MB package đã cài), cùng `main.py` và `utils/mock_llm.py`.
  - Tạo user `appuser` và chạy `USER appuser` để không chạy bằng root.
  - Thêm `HEALTHCHECK`, chạy uvicorn với 2 worker.
- **Vì sao image nhỏ hơn:**
  1. Base là `python:3.11-slim` thay vì `python:3.11` đầy đủ.
  2. `gcc`, `libpq-dev`, cache của apt và các file trung gian của quá trình build chỉ nằm ở stage `builder`, không vào image cuối.
  3. Image cuối chỉ chứa những gì cần để **chạy** app.

  Nhờ vậy image nhỏ hơn, attack surface hẹp hơn (không có compiler), và pull hoặc deploy nhanh hơn.

```bash
docker build -f 02-docker/production/Dockerfile -t my-agent:advanced .
```

```text
$ docker images | grep my-agent
my-agent    advanced   551ec64e9ae8   6 seconds ago   188MB
my-agent    develop    1729f7fd9886   2 minutes ago   1.17GB
```

#### Image size comparison

Số đo từ `docker image inspect --format '{{.Size}}'` (1 MB = 10^6 byte, cùng đơn vị với `docker images`):

| Image | Dockerfile | Size |
|---|---|---:|
| `my-agent:develop` | single-stage, `python:3.11` | **1169.5 MB** (1 169 510 072 B) |
| `my-agent:advanced` | multi-stage, `python:3.11-slim` | **188.4 MB** (188 415 952 B) |
| (tham khảo) stage `builder` | `--target builder` | 404.8 MB |

- **Develop:** 1169.5 MB
- **Production:** 188.4 MB
- **Chênh lệch:** 981.1 MB. Image production **nhỏ hơn 83.9%**, khoảng 6.2 lần. Ngay cả so với stage `builder` (cũng dùng base slim), runtime vẫn nhỏ hơn 53.5%, nhờ bỏ được gcc và các công cụ build.

Chạy thử image production:

```text
$ docker run -d --name cp2-adv -p 8000:8000 my-agent:advanced
$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question": "What is Docker?"}'
HTTP/1.1 200 OK
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}

$ curl http://localhost:8000/ready
{"ready":true}

$ docker exec cp2-adv whoami
appuser

$ docker ps --filter name=cp2-adv --format '{{.Status}}'
Up 5 seconds (healthy)
```

Nhận xét:
- Container chạy bằng **`appuser`** chứ không phải root.
- `HEALTHCHECK` hoạt động, Docker báo trạng thái `(healthy)`.
- Image runtime **không còn `gcc`**, nhưng vẫn còn `pip`, vì `pip` có sẵn trong base `python:3.11-slim`.

### Exercise 2.4: Docker Compose stack

```bash
cd 02-docker/production
touch .env.local          # compose yêu cầu file này (env_file), để trống vì dùng mock LLM
docker compose -p k5-day14-docker up -d --build
```

Các service được khởi động:

```text
SERVICE   IMAGE                   STATUS                    PORTS
agent     k5-day14-docker-agent   Up 8 seconds (healthy)    8000/tcp
nginx     nginx:alpine            Up 8 seconds              0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
qdrant    qdrant/qdrant:v1.9.0    Up 19 seconds (healthy)   6333-6334/tcp
redis     redis:7-alpine          Up 19 seconds (healthy)   6379/tcp
```

#### Architecture diagram

```text
                    Host (macOS)
                        │
             :80 / :443 │  (chỉ Nginx publish port ra ngoài)
                        ▼
┌──────────────────────────────────────────────────────────────────┐
│  network "internal" (bridge)                                     │
│                                                                  │
│   ┌──────────────┐  proxy_pass         ┌─────────────────────┐   │
│   │ nginx:alpine │ ──────────────────▶ │ agent (FastAPI)     │   │
│   │ reverse proxy│  upstream           │ uvicorn :8000       │   │
│   │ rate limit   │  agent_backend      │ 2 workers, appuser  │   │
│   │ 10 r/s/IP    │  = agent:8000       └─────────┬───────────┘   │
│   │ + sec headers│                               │               │
│   └──────────────┘         REDIS_URL=            │ QDRANT_URL=   │
│                            redis://redis:6379/0  │ http://qdrant:6333
│                                  ┌───────────────┴──────┐        │
│                                  ▼                      ▼        │
│                     ┌────────────────────┐  ┌──────────────────┐ │
│                     │ redis:7-alpine     │  │ qdrant v1.9.0    │ │
│                     │ :6379, 256MB LRU   │  │ :6333 vector DB  │ │
│                     │ vol: redis_data    │  │ vol: qdrant_data │ │
│                     └────────────────────┘  └──────────────────┘ │
└──────────────────────────────────────────────────────────────────┘

Thứ tự khởi động (depends_on):
redis (healthy) + qdrant (healthy) → agent (healthy) → nginx
```

**Các service giao tiếp với nhau thế nào:**
- Cả 4 service cùng nằm trong network bridge `internal`. Docker có DNS nội bộ, nên các service gọi nhau bằng **tên service**: `agent`, `redis`, `qdrant`. Kiểm tra bằng `docker network inspect`, được các IP: redis 172.29.0.2, qdrant 172.29.0.3, agent 172.29.0.4, nginx 172.29.0.5.
- Client chỉ vào được qua **Nginx** (cổng 80). Agent **không publish port** ra host: `curl localhost:8000` từ máy host không kết nối được. Nginx `proxy_pass` tới `upstream agent_backend { server agent:8000; }`.
- Agent kết nối tới Redis và Qdrant qua URL trong biến môi trường (`REDIS_URL`, `QDRANT_URL`). Kiểm tra kết nối agent → Redis từ trong container agent: gửi `PING` tới `redis:6379` và nhận về `+PONG`.
- `depends_on` kèm `condition: service_healthy` đảm bảo agent chỉ khởi động khi Redis và Qdrant đã healthy.

Test qua Nginx:

```text
$ curl -i http://localhost/health
HTTP/1.1 200 OK
Server: nginx
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"status":"ok","uptime_seconds":7.4,"version":"2.0.0","timestamp":"2026-11-26T07:21:29.257514"}

$ curl -i http://localhost/ask -X POST -H "Content-Type: application/json" -d '{"question": "Explain microservices"}'
HTTP/1.1 200 OK
Server: nginx
{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

- Header `Server: nginx` và các security header cho thấy request đã đi qua Nginx. Nginx còn ẩn version nhờ `server_tokens off`.
- Thử rate limit của Nginx (`rate=10r/s`, `burst=20`) bằng 40 request liên tiếp vào `/`. Khoảng 23 request đầu trả 200, sau đó chủ yếu là **429**. Log Nginx ghi `limiting requests, excess: 20.880 by zone "api_limit"`.

```text
200 ×23, rồi 429 429 429 429 200 429 ... (thỉnh thoảng có 200 khi bucket hồi lại 1 token sau mỗi 100 ms)
```

Dọn stack: `docker compose -p k5-day14-docker down -v`.

#### Nhận xét thêm về stack

- `main.py` **không hề dùng Redis hay Qdrant**: không import client nào, cũng không đọc `REDIS_URL`. Hai service này đang chạy không, chỉ để minh hoạ kiến trúc. State thật sẽ đưa vào Redis ở Part 5 và Part 6.
- Compose khai báo `version: "3.9"`, nhưng Compose v2 đã bỏ trường này nên chỉ in cảnh báo.
- Port 443 được publish nhưng `nginx.conf` chỉ `listen 80`, chưa có chứng chỉ TLS, nên 443 chưa dùng được.
- `upstream` chỉ có `server agent:8000`. Muốn scale nhiều instance, có thể dựa vào DNS của Docker (`--scale agent=3`, Nginx resolve tên `agent` ra nhiều IP lúc khởi động) hoặc liệt kê từng instance.

## Part 3: Cloud Deployment

_(chưa làm)_

## Part 4: API Security

Môi trường chạy: Python 3.12.6 trong `.venv`, cài thêm `pyjwt` và `redis`. Bản develop và bản production lần lượt chạy trên cổng 8000; tắt hẳn bản cũ rồi mới bật bản mới. Token JWT trong các output bên dưới đã được che thành `eyJ***MASKED***`.

### Exercise 4.1: API Key authentication

File: `04-api-gateway/develop/app.py`

- **API key được kiểm tra ở đâu?**
  - Hàm dependency `verify_api_key` (dòng 39–54) đọc header `X-API-Key` thông qua `APIKeyHeader(name="X-API-Key", auto_error=False)` (dòng 36).
  - Endpoint `/ask` dùng hàm này qua `Depends(verify_api_key)` (dòng 70), nên request chỉ chạy vào handler khi key hợp lệ.
  - `/` và `/health` để công khai, vì nền tảng cloud cần gọi `/health` mà không có key.
- **Nếu sai key thì sao?**
  - Không có header: trả **401** `Missing API key...` (dòng 44–48).
  - Có header nhưng sai key: trả **403** `Invalid API key.` (dòng 49–53).
  - Trong cả hai trường hợp, request bị chặn trước khi gọi LLM, nên không tốn tiền.
- **Làm sao rotate key?**
  - Key đọc từ biến môi trường `AGENT_API_KEY` (dòng 35), không nằm trong code. Để rotate: đặt giá trị mới trên dashboard hoặc trong secret manager, restart (hoặc redeploy) app, rồi gửi key mới cho client.
  - Muốn rotate **không downtime** thì cho app chấp nhận đồng thời 2 key trong một khoảng chuyển tiếp, ví dụ `AGENT_API_KEYS=old,new`. Khi mọi client đã chuyển sang key mới thì gỡ key cũ.
  - Lưu ý: bản này có giá trị mặc định `"demo-key-change-in-production"`. Nếu quên đặt biến môi trường, app vẫn chạy với một key ai cũng biết. Bản production nên **fail fast** (dừng ngay khi khởi động) nếu thiếu key.
  - Ngoài ra dòng 91 `print(f"API Key: {API_KEY}")` in key ra log khi khởi động, lặp lại đúng anti-pattern của Part 1.

Chạy bản develop với `AGENT_API_KEY=secret-key-123 python app.py`:

```text
$ curl -i http://localhost:8000/ask -X POST -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 401 Unauthorized
content-type: application/json

{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

$ curl -i http://localhost:8000/ask -X POST -H "X-API-Key: wrong-key" -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 403 Forbidden
content-type: application/json

{"detail":"Invalid API key."}

$ curl -i http://localhost:8000/ask -X POST -H "X-API-Key: secret-key-123" -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 200 OK
content-type: application/json

{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}

$ curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/health
200
```

### Exercise 4.2: JWT authentication

File: `04-api-gateway/production/auth.py`

**Luồng JWT:**

1. Client gửi `POST /auth/token` kèm `{"username","password"}`. Hàm `authenticate_user` so khớp với `DEMO_USERS`. Sai thông tin thì trả **401** `Invalid credentials`.
2. `create_token` tạo payload `{sub, role, iat, exp = now + 60 phút}`, rồi ký bằng **HS256** với `JWT_SECRET` (lấy từ biến môi trường).
3. Client gửi token trong header `Authorization: Bearer <token>` ở mọi request.
4. `verify_token` gọi `jwt.decode(...)` để kiểm tra chữ ký và hạn dùng, rồi trả về `{username, role}`. Server **không cần tra database** cho mỗi request, nên auth là stateless và scale ngang dễ dàng.

Kết quả chạy (dùng `/auth/token` với `student`/`demo123`, theo lưu ý K5):

```text
$ curl -i http://localhost:8000/token -X POST ... -d '{"username":"admin","password":"secret"}'
HTTP/1.1 404 Not Found              ← endpoint/tài khoản trong CODE_LAB không tồn tại

$ curl -i http://localhost:8000/auth/token -X POST -H "Content-Type: application/json" -d '{"username":"student","password":"wrong"}'
HTTP/1.1 401 Unauthorized
{"detail":"Invalid credentials"}

$ curl -i http://localhost:8000/auth/token -X POST -H "Content-Type: application/json" -d '{"username":"student","password":"demo123"}'
HTTP/1.1 200 OK
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"access_token":"eyJ***MASKED***","token_type":"bearer","expires_in_minutes":60,"hint":"Include in header: Authorization: Bearer eyJ***MASKED***"}
```

Phần payload của token, decode mà không verify chữ ký: `{'sub': 'student', 'role': 'user', 'iat': 1795678170, 'exp': 1795681770}`. `exp - iat = 3600` giây, tức 60 phút. Payload chỉ được **mã hoá base64, không bị mã hoá bảo mật**, nên ai cầm token cũng đọc được nội dung. Không bao giờ được đưa thông tin bí mật vào payload.

Gọi `/ask`:

```text
$ curl -i http://localhost:8000/ask -X POST -H "Content-Type: application/json" -d '{"question":"Explain JWT"}'
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer
{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

$ curl -i http://localhost:8000/ask -X POST -H "Authorization: Bearer abc.def.ghi" -H "Content-Type: application/json" -d '{"question":"Explain JWT"}'
HTTP/1.1 403 Forbidden
{"detail":"Invalid token."}

$ curl -i http://localhost:8000/ask -X POST -H "Authorization: Bearer eyJ***MASKED***" -H "Content-Type: application/json" -d '{"question":"Explain JWT"}'
HTTP/1.1 200 OK
{"question":"Explain JWT","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","usage":{"requests_remaining":9,"budget_remaining_usd":1.9e-05}}
```

Gửi `{"question":""}` thì bị **422**, vì Pydantic kiểm tra `min_length=1, max_length=1000`.

Kiểm tra phân quyền theo role: `GET /admin/stats` với token của `student` trả **403** `Admin only`, với token của `teacher` (role `admin`) trả **200**.

### Exercise 4.3: Rate limiting

File: `04-api-gateway/production/rate_limiter.py`

- **Thuật toán:** **Sliding Window Log**. Mỗi user có một `deque` lưu timestamp của các request.
  - Mỗi lần gọi, loại bỏ các timestamp cũ hơn `now - 60s`. Nếu `len(window) >= max_requests` thì trả **429**, kèm header `Retry-After` và `X-RateLimit-*`.
  - Docstring gọi đây là "Sliding Window Counter", nhưng code thực tế lưu từng timestamp nên đúng ra là *log*. Đây cũng không phải token bucket. Kiểu này chính xác hơn fixed window: không có hiện tượng dồn gấp đôi request ở ranh giới hai cửa sổ.
- **Giới hạn:** user thường (`student`) được **10 request/60 giây**. Admin (`teacher`) được **100 request/60 giây** (dòng 86–87).
- **Bypass cho admin:**
  - `app.py` dòng 141 chọn `rate_limiter_admin if role == "admin" else rate_limiter_user`, tức là dùng **một limiter riêng có hạn mức cao hơn**, chứ không bỏ hẳn giới hạn.
  - Role được lấy từ JWT đã ký, nên client không tự sửa được.
  - Muốn bỏ hẳn giới hạn thì thêm `if role == "admin": skip`. Tuy vậy, giữ một giới hạn cao vẫn an toàn hơn, phòng trường hợp token admin bị lộ.
  - Kiểm chứng: `teacher` gửi 15 request liên tiếp, cả 15 đều trả 200.

Vòng lặp 20 request bằng token của `student` (lấy token mới, server vừa khởi động lại):

```text
req  1: HTTP 200  remaining=9
req  2: HTTP 200  remaining=8
req  3: HTTP 200  remaining=7
req  4: HTTP 200  remaining=6
req  5: HTTP 200  remaining=5
req  6: HTTP 200  remaining=4
req  7: HTTP 200  remaining=3
req  8: HTTP 200  remaining=2
req  9: HTTP 200  remaining=1
req 10: HTTP 200  remaining=0
req 11: HTTP 429  {'error': 'Rate limit exceeded', 'limit': 10, 'window_seconds': 60, 'retry_after_seconds': 58}
...
req 20: HTTP 429  {'error': 'Rate limit exceeded', 'limit': 10, 'window_seconds': 60, 'retry_after_seconds': 58}
```

Response 429 đầy đủ:

```text
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795678232
retry-after: 59
content-type: application/json

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

**Hạn chế:** state nằm trong RAM (`defaultdict(deque)`), nên:
1. Restart là mất toàn bộ bộ đếm.
2. Chạy N instance thì mỗi user thực tế được tới 10×N request/phút.
3. `deque` của user không bao giờ bị xoá, nên bộ nhớ tăng dần theo số user.

Bản production thật cần đưa state vào Redis, ví dụ ZSET dùng timestamp làm score, kết hợp `ZREMRANGEBYSCORE` + `ZCARD` + `ZADD` trong một pipeline hoặc script Lua.

### Exercise 4.4: Cost guard

**Cách làm của `cost_guard.py` có sẵn:**
- Đếm token in-memory theo **ngày**. Mỗi user được $1/ngày, toàn hệ thống được $10/ngày.
- Gọi `check_budget()` **trước** khi gọi LLM. Vượt budget của user thì trả **402 Payment Required**. Vượt budget toàn hệ thống thì trả **503**.
- Gọi `record_usage()` **sau** khi gọi LLM, tính chi phí theo giá GPT-4o-mini.
- Log cảnh báo khi đã dùng 80% budget.

Kiểm chứng `/me/usage` sau 10 request: `"requests":10,"input_tokens":40,"output_tokens":296,"cost_usd":0.000184,"budget_remaining_usd":0.999816`.

**Lỗi phát hiện được:**
- `app.py` dòng 160 trả `"budget_remaining_usd": usage.total_cost_usd`, tức là trả **số tiền đã dùng** chứ không phải số còn lại. Output cho thấy `budget_remaining_usd` *tăng* sau mỗi request (1.9e-05 → 3.7e-05 → ...).
- Phần reset global budget theo ngày chưa được cài: có biến `_global_today` nhưng không được dùng. Vì vậy `_global_cost` không bao giờ quay về 0.

**Cài `check_budget` theo đề ($10/tháng, lưu trong Redis, reset đầu tháng):**

```python
import os
from datetime import datetime, timezone
import redis

r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
MONTHLY_BUDGET_USD = float(os.getenv("MONTHLY_BUDGET_USD", "10"))
TTL_SECONDS = 32 * 24 * 3600

# Đọc, so sánh và cộng trong MỘT script Lua → atomic, không bị race khi nhiều instance gọi cùng lúc
_RESERVE = r.register_script("""
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
local cost = tonumber(ARGV[1])
local budget = tonumber(ARGV[2])
if current + cost > budget then
  return 0
end
redis.call('INCRBYFLOAT', KEYS[1], cost)
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[3]))
return 1
""")

def _key(user_id: str, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"budget:{user_id}:{now:%Y-%m}"        # mỗi tháng (UTC) một key → tự reset

def check_budget(user_id: str, estimated_cost: float) -> bool:
    """True nếu còn budget (đồng thời trừ estimated_cost), False nếu vượt $10/tháng."""
    if estimated_cost < 0:
        raise ValueError("estimated_cost must be >= 0")
    return _RESERVE(keys=[_key(user_id)],
                    args=[estimated_cost, MONTHLY_BUDGET_USD, TTL_SECONDS]) == 1
```

**Giải thích:**
- **Lưu trong Redis:** mọi instance của agent dùng chung một bộ đếm. Restart hay scale đều không làm mất state hoặc đếm sai.
- **Reset đầu tháng:**
  - Tên key có chứa tháng (`budget:<user>:2026-11`). Sang tháng 12, app tự dùng key `...:2026-12` bắt đầu từ 0, không cần cron job.
  - `EXPIRE` 32 ngày để key của tháng cũ tự bị xoá.
  - Dùng tháng theo **UTC** để mọi instance ra cùng một kết quả, dù server đặt ở múi giờ nào.
- **Atomic:**
  - Đáp án mẫu trong CODE_LAB làm `GET` rồi mới `INCRBYFLOAT`, tách thành hai bước. Khi nhiều request chạy song song, các request đều đọc được cùng một giá trị cũ, nên cùng qua được bước kiểm tra.
  - Script Lua chạy atomic trên Redis, nên tránh được tình huống này.
- **Kiểm tra *trước* khi gọi LLM:** dùng `estimated_cost`, tức là giữ trước số tiền. Sau khi có số token thật, có thể điều chỉnh lại phần chênh lệch bằng `INCRBYFLOAT`.
- Nếu `check_budget` trả `False`, endpoint trả **402**, đúng tiêu chí "Cost guard" của Part 6.

**Kiểm thử với Redis thật** (container `redis:7-alpine` tạm):

```text
1) 4 x $2.5 : [True, True, True, True] spent = 10.0
2) +$0.01   : False spent = 10.0
3) key/TTL  : budget:test-user:2026-11 ttl_days = 32.0
4) next month key: budget:test-user:2026-12 -> spent 0, budget reset
5) race 100 x $0.15: accepted = 66 spent = 9.9 (<= 10)
```

So sánh với đáp án mẫu (GET rồi INCRBYFLOAT) trong cùng bài test race:

```text
naive race 100 x $0.15: accepted = 71 spent = 10.65   ← vượt budget $0.65
```

Bản dùng Lua chấp nhận đúng 66 request (66 × $0.15 = $9.90). Bản mẫu chấp nhận 71 request và **vượt budget**, vì có 32 thread cùng đọc giá trị cũ.

### Rate limit và cost guard: vì sao cần cả hai?

- **Rate limit bảo vệ *tốc độ*.** Nó chặn spam, chặn brute-force, tránh làm quá tải server và LLM provider. Nhưng nếu một user gửi đều 10 request/phút suốt cả tháng, hoặc gửi những prompt rất dài, thì vẫn không vượt rate limit mà hoá đơn vẫn có thể rất lớn.
- **Cost guard bảo vệ *tiền*.** Nó đặt trần tổng chi phí theo user và theo toàn hệ thống trong một chu kỳ (ngày hoặc tháng). Nhưng nó không ngăn được việc dồn dập request trong vài giây.
- Hai lớp này bổ sung cho nhau. Thứ tự kiểm tra hợp lý:
  1. **Auth** (401/403)
  2. **Rate limit** (429)
  3. **Budget** (402)
  4. Gọi LLM
  5. Ghi nhận chi phí thật

  Request bị chặn ở lớp càng sớm thì càng tốn ít tài nguyên.

## Part 5: Scaling & Reliability

Môi trường chạy: bản develop chạy bằng `.venv` trên cổng 8000 (cài thêm `psutil==6.0.0`). Bản production chạy stack Docker Compose với project `-p k5-day14-scaling`.

### Exercise 5.1: Health checks

File: `05-scaling-reliability/develop/app.py`. Hai endpoint này đã có sẵn, mình đọc và chạy thử.

- **`GET /health`, liveness probe** (dòng 104–144):
  - Trả 200 nếu tiến trình còn sống, kèm `uptime`, `version`, `environment`, `timestamp`.
  - Có thêm phần `checks.memory` dùng `psutil`. Khi RAM vượt 90% thì `status` chuyển thành `"degraded"`, nhưng **mã HTTP vẫn là 200**.
  - Như vậy là đúng: liveness chỉ nên fail khi tiến trình thật sự hỏng. Nếu fail vì một phụ thuộc bên ngoài, nền tảng sẽ restart container liên tục mà không giải quyết được gì.
- **`GET /ready`, readiness probe** (dòng 147–168):
  - Trả **503** khi `_is_ready = False`. Cờ này là `False` trong lúc khởi động (trước khi lifespan startup chạy xong) và được đặt lại thành `False` khi bắt đầu shutdown.
  - Khi sẵn sàng thì trả 200, kèm `in_flight_requests`.
  - Load balancer dựa vào endpoint này để quyết định có gửi traffic vào instance hay không.

```text
$ curl -i http://localhost:8000/health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":2.8,"version":"1.0.0","environment":"development","timestamp":"2026-11-26T07:35:17.834692+00:00","checks":{"memory":{"status":"ok","used_percent":79.3}}}

$ curl -i http://localhost:8000/ready
HTTP/1.1 200 OK
{"ready":true,"in_flight_requests":1}
```

`in_flight_requests` là 1 vì middleware `track_requests` đếm luôn chính request `/ready` đang chạy.

Bản production (`production/app.py`, dòng 187–215) làm readiness đúng nghĩa hơn: `/ready` **ping Redis**, và trả **503 `Redis not available`** nếu Redis chết. Còn `/health` chỉ báo `"degraded"` chứ không fail. Đây chính là yêu cầu của Part 6: `/health` vẫn 200 khi mất Redis, còn `/ready` trả 503.

### Exercise 5.2: Graceful shutdown

Cơ chế trong `develop/app.py`:

1. `uvicorn.run(..., timeout_graceful_shutdown=30)`. Khi nhận SIGTERM, uvicorn **đóng socket listen** (không nhận kết nối mới), rồi **chờ các request đang chạy hoàn thành**, tối đa 30 giây.
2. Sau đó chạy phần shutdown của `lifespan`: đặt `_is_ready = False` để `/ready` trả 503, chờ `_in_flight_requests` về 0 (tối đa 30 giây), rồi log `Shutdown complete`. Đây là chỗ để đóng kết nối DB hoặc Redis.
3. Tiến trình thoát với exit code 0.

Test: gửi một request `Long task` (mock LLM của bản develop mất khoảng 3 giây), rồi gửi SIGTERM sau 0.5 giây:

```bash
python app.py &  PID=$!
curl -X POST "http://localhost:8000/ask?question=Long%20task" &
sleep 0.5; kill -TERM $PID
```

```text
SIGTERM sent to 21187
### new request after SIGTERM:
 [HTTP 000] -> refused (exit 56)          ← request mới bị từ chối
### in-flight request result:
{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."} [HTTP 200, 3.054170s]
process exit code: 0
```

Log server:

```text
INFO:     Shutting down
INFO:     127.0.0.1:55814 - "POST /ask?question=Long%20task HTTP/1.1" 200 OK
INFO:     Waiting for application shutdown.
2026-11-26 14:35:21,031 INFO 🔄 Graceful shutdown initiated...
2026-11-26 14:35:21,031 INFO ✅ Shutdown complete
INFO:     Application shutdown complete.
INFO:     Finished server process [21187]
2026-11-26 14:35:21,031 INFO Received signal 15 — uvicorn will handle graceful shutdown
```

**Kết luận:** request đang chạy **hoàn thành với 200** (mất 3.05 giây, dù SIGTERM đến ở giây 0.5). Request mới bị từ chối. App thoát sạch với exit code 0.

**Quan sát thêm:**
- `handle_sigterm` (dòng 175–187) **không** được gọi lúc nhận signal, mà chỉ chạy ở **cuối cùng**, sau `Finished server process`.
  - Lý do: `uvicorn.run()` tự cài signal handler của nó, đè lên handler của app. Khi tắt xong, uvicorn mới gọi lại signal cho handler cũ.
  - Vậy logic dọn dẹp **phải đặt trong `lifespan`**, không đặt trong `signal.signal`.
- Vòng lặp "Waiting for in-flight requests" không in dòng nào, vì uvicorn đã chờ request xong *trước khi* chạy phần shutdown của lifespan.
- Đây là lỗi nghiêm trọng hơn: `ask_agent` là `async def` nhưng gọi `ask()`, và `ask()` dùng `time.sleep(3)` (blocking), nên **cả event loop bị chặn**. Đo được:
  - `GET /health` gửi trong lúc có một `/ask` đang chạy phải chờ **2.85 giây** mới nhận được 200.
  - 3 request `/ask` gửi đồng thời chạy **tuần tự**, kết thúc sau 3.0, 6.0 và 9.1 giây. Đáng lẽ cả ba chỉ mất khoảng 3 giây.

  Nếu probe có timeout ngắn, nền tảng sẽ tưởng app đã chết. Cách sửa: khai báo handler là `def` (FastAPI tự chạy trong threadpool), hoặc dùng `await asyncio.to_thread(ask, q)`, hoặc dùng client LLM bất đồng bộ.

### Exercise 5.3: Stateless design

File: `05-scaling-reliability/production/app.py`. Code này đã được viết theo kiểu stateless. Mình phân tích lại như sau:

- **Anti-pattern:**
  - Viết `conversation_history = {}` trong RAM thì mỗi instance có một dict riêng.
  - Request 1 của user rơi vào instance A, request 2 rơi vào instance B, và B không thấy lịch sử. Restart hoặc deploy thì mất hết.
  - Không scale ngang được, và không thể "kill an toàn" bất kỳ instance nào.
- **Cách làm đúng trong code:**
  - Mọi state của session nằm trong Redis: `save_session` dùng `SETEX session:<id> 3600 <json>`, `load_session` dùng `GET`.
  - `append_to_history` giữ tối đa 20 message.
  - Instance chỉ giữ `INSTANCE_ID` để debug, nên **bất kỳ instance nào cũng phục vụ được bất kỳ request nào**.
  - TTL 3600 giây giúp session cũ tự hết hạn.
- **Vấn đề còn lại khi đọc code:**
  1. **Fallback ngầm về RAM.** Nếu lúc import không kết nối được Redis, app chỉ `print` cảnh báo rồi dùng `_memory_store`, tức là lặng lẽ quay lại trạng thái stateful. Production nên **fail fast**, hoặc trả `/ready` 503 thay vì fallback.
  2. **Race khi cập nhật history.** `append_to_history` làm `GET` → sửa trong Python → `SETEX`. Hai request cùng session chạy song song trên hai instance có thể ghi đè lên nhau và mất message. Cách đúng hơn là dùng Redis list với `RPUSH` + `LTRIM` + `EXPIRE` trong một pipeline (atomic, không cần đọc trước):

     ```python
     def append_to_history(session_id, role, content):
         key = f"history:{session_id}"
         msg = json.dumps({"role": role, "content": content,
                           "timestamp": datetime.now(timezone.utc).isoformat()})
         pipe = _redis.pipeline()
         pipe.rpush(key, msg)
         pipe.ltrim(key, -20, -1)      # giữ 20 message cuối
         pipe.expire(key, 3600)
         pipe.execute()

     def load_history(session_id):
         return [json.loads(m) for m in _redis.lrange(f"history:{session_id}", 0, -1)]
     ```
  3. `uvicorn.run(..., reload=True)` ở dòng 220 chỉ ảnh hưởng khi chạy `python app.py`. Container chạy bằng `CMD uvicorn app:app` nên không bị ảnh hưởng.

### Exercise 5.4: Load balancing

Theo lưu ý K5, stack mở cổng 8080 và endpoint là `POST /chat`.

**Sự cố cổng 8080:** trên máy mình, cổng 8080 đang bị container `p151-cloud-gateway-1` của một project khác chiếm, nên `up` báo `Bind for 0.0.0.0:8080 failed: port is already allocated`.
- Mình **không sửa file nào của đề**. Thay vào đó dùng thêm một file override chỉ đổi cổng host của Nginx sang 8081:

  ```yaml
  # compose.port8081.yml (file tạm, không nằm trong repo)
  services:
    nginx:
      ports: !override
        - "8081:80"
  ```

  ```bash
  cd 05-scaling-reliability/production
  touch .env.local
  docker compose -p k5-day14-scaling -f docker-compose.yml -f compose.port8081.yml up -d --build --scale agent=3
  ```
- Trên máy không bị trùng cổng thì lệnh gốc của đề chạy bình thường ở 8080.

```text
NAME                       STATUS                    PORTS
k5-day14-scaling-agent-1   Up 25 seconds (healthy)   8000/tcp
k5-day14-scaling-agent-2   Up 24 seconds (healthy)   8000/tcp
k5-day14-scaling-agent-3   Up 25 seconds (healthy)   8000/tcp
k5-day14-scaling-nginx-1   Up 12 seconds             0.0.0.0:8081->80/tcp
k5-day14-scaling-redis-1   Up 35 seconds (healthy)   6379/tcp
```

Gửi 10 request qua Nginx. Header `X-Served-By` (là `$upstream_addr`) và trường `served_by` cho thấy **round-robin** đều giữa 3 instance:

```text
req  1 X-Served-By: 172.29.0.5:8000 served_by=instance-de33c3 storage=redis
req  2 X-Served-By: 172.29.0.4:8000 served_by=instance-19af20 storage=redis
req  3 X-Served-By: 172.29.0.3:8000 served_by=instance-6ada2e storage=redis
req  4 X-Served-By: 172.29.0.5:8000 served_by=instance-de33c3 storage=redis
req  5 X-Served-By: 172.29.0.4:8000 served_by=instance-19af20 storage=redis
req  6 X-Served-By: 172.29.0.3:8000 served_by=instance-6ada2e storage=redis
req  7 X-Served-By: 172.29.0.5:8000 served_by=instance-de33c3 storage=redis
req  8 X-Served-By: 172.29.0.4:8000 served_by=instance-19af20 storage=redis
req  9 X-Served-By: 172.29.0.3:8000 served_by=instance-6ada2e storage=redis
req 10 X-Served-By: 172.29.0.5:8000 served_by=instance-de33c3 storage=redis
```

Đếm `POST /chat` trong `docker compose -p k5-day14-scaling logs agent` sau toàn bộ bài test (19 request): agent-1 nhận **6**, agent-2 nhận **6**, agent-3 nhận **7**.

**Cách Nginx phân tải:**
- Trong `upstream agent_cluster { server agent:8000; }`, Docker DNS phân giải tên `agent` ra 3 IP, và Nginx round-robin giữa 3 IP đó.
- `proxy_next_upstream error timeout http_503` cùng `proxy_next_upstream_tries 3` giúp tự chuyển sang instance khác khi một instance lỗi.

### Exercise 5.5: Test stateless

Chạy `python test_stateless.py`. Script gốc gọi `localhost:8080`, nên mình chạy nó với URL thay bằng 8081 lúc chạy, không sửa file:

```text
============================================================
Stateless Scaling Demo
============================================================

Session ID: a7285067-ac09-4564-9d93-670e63f4a084

Request 1: [instance-de33c3]
  Q: What is Docker?
Request 2: [instance-19af20]
  Q: Why do we need containers?
Request 3: [instance-6ada2e]
  Q: What is Kubernetes?
Request 4: [instance-de33c3]
  Q: How does load balancing work?
Request 5: [instance-19af20]
  Q: What is Redis used for?
------------------------------------------------------------
Total requests: 5
Instances used: {'instance-19af20', 'instance-6ada2e', 'instance-de33c3'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
  [user]: What is Docker?...
  [assistant]: Container là cách đóng gói app để chạy ở mọi nơi. Build once...
  ...
  [user]: What is Redis used for?...
  [assistant]: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đ...

✅ Session history preserved across all instances via Redis!
```

**Giải thích kết quả:**
- 5 câu hỏi cùng một `session_id` được **cả 3 instance** phục vụ, theo thứ tự de33c3 → 19af20 → 6ada2e → de33c3 → 19af20.
- Dù vậy, history đọc lại vẫn đủ **10 message** (5 user + 5 assistant) và đúng thứ tự, vì không instance nào giữ history trong RAM. Mọi instance đều đọc và ghi cùng key `session:<id>` trong Redis.
- Nếu state nằm trong RAM, instance thứ hai sẽ thấy session rỗng.

**Thử thêm: kill 1 instance giữa cuộc hội thoại.** Đề gốc mô tả bước này, nhưng script không tự làm nên mình làm tay.
- Chạy `docker stop k5-day14-scaling-agent-2` (gửi SIGTERM; container này là `instance-de33c3`). Container tắt sạch trong 0.43 giây:

  ```text
  INFO:     Waiting for application shutdown.
  INFO:app:Instance instance-de33c3 shutting down
  INFO:     Application shutdown complete.
  ```
- Sau đó gửi tiếp 4 câu với **cùng session**:

  ```text
  turn 7  served_by instance-19af20 [HTTP 200 0.126382s]
  turn 8  served_by instance-6ada2e [HTTP 200 0.108077s]
  turn 9  served_by instance-19af20 [HTTP 200 60.198243s]   ← chậm 60 giây!
  turn 10 served_by instance-6ada2e [HTTP 200 0.115509s]
  ```
- `GET /chat/<id>/history` trả `count 18`, gồm đủ 9 câu user (5 câu ban đầu và 4 câu "After kill"). Key trong Redis có TTL khoảng 3593 giây.
- **Kết luận:** session **không bị mất** khi một instance chết, và mọi request vẫn trả 200.

**Vì sao turn 9 mất 60 giây?** Log Nginx ghi:

```text
[error] upstream timed out (110: Operation timed out) while connecting to upstream, ... upstream: "http://172.29.0.5:8000/chat"
```

- Nginx chỉ phân giải tên `agent` **một lần lúc khởi động**. Directive `resolver 127.0.0.11 valid=10s` không có tác dụng với `server agent:8000` trong khối `upstream` nếu không có tham số `resolve`.
- Vì vậy khi agent-2 đã tắt, Nginx vẫn gửi tới IP cũ `172.29.0.5`. IP này không còn ai trả lời, nên Nginx chờ hết `proxy_connect_timeout` mặc định **60 giây** rồi mới chuyển sang instance khác, nhờ `proxy_next_upstream`.
- Hệ thống tự phục hồi được nhưng người dùng phải chờ 60 giây.

Cách sửa:
1. Đặt `proxy_connect_timeout 2s;`.
2. Thêm `max_fails=1 fail_timeout=10s` để đánh dấu instance hỏng và bỏ qua nó một thời gian.
3. Hoặc dùng `server agent:8000 resolve;` (Nginx ≥ 1.27.3) để phân giải lại DNS định kỳ.

Trong K8s hay trên cloud thì readiness probe sẽ gỡ endpoint khỏi load balancer trước khi gửi SIGTERM.

Dọn stack: `docker compose -p k5-day14-scaling down -v`.

### Checkpoint 5: Trả lời câu hỏi

- **Liveness (`/health`) khác readiness (`/ready`) ở đâu?**

  | | Liveness `/health` | Readiness `/ready` |
  |---|---|---|
  | Câu hỏi | "Tiến trình còn sống không?" | "Có nên gửi traffic vào instance này không?" |
  | Fail thì | Nền tảng **restart** container | Load balancer **ngừng gửi traffic**, nhưng không restart |
  | Nên kiểm tra | Chỉ bản thân tiến trình (event loop còn trả lời) | Phụ thuộc bên ngoài (Redis, DB, model đã load), có đang shutdown không |
  | Khi Redis chết | Vẫn **200** (restart không chữa được Redis) | **503** |

- **Vì sao state trong RAM hỏng khi chạy nhiều instance?**
  - Mỗi instance là một tiến trình với bộ nhớ riêng. Load balancer gửi các request của cùng một user tới các instance khác nhau (thấy rõ qua round-robin ở trên), nên mỗi instance chỉ có một mảnh state.
  - Instance bị restart, deploy hay scale xuống thì mảnh state đó mất luôn.
  - Rate limiter hay cost guard lưu trong RAM sẽ cho phép gấp N lần giới hạn khi chạy N instance.
  - Đưa state vào một kho dùng chung như Redis thì mọi instance thấy cùng một dữ liệu. Khi đó có thể thêm, bớt hay kill instance tuỳ ý, như bài test kill agent-2 ở trên.

---

## Part 6: Final Project

Code nằm trong `06-lab-complete/`. Kết quả chấm bằng `python check_production_ready.py`, chạy đầy đủ (có Docker, không dùng `--skip-docker`), trên macOS, Python 3.12.6, Docker 27.4.0:

### Output `check_production_ready.py`: 📋 Checklist Deliverable

```text
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

Một số dòng chi tiết trong output: image **207 MB** (đơn vị MiB của script, tương đương 217 MB theo `docker images`). `429 sau 5 request thành công (RATE_LIMIT_PER_MINUTE=5)`. `state nằm trong Redis — restart agent vẫn bị 429`. `402 ở request thứ 2`. `15 dòng JSON`. `SIGTERM lúc đang có request → request vẫn 200 ... exit code 0`. `docker stop ... exit code 0, 0.5s`.

### Thiết kế

| File | Cách làm |
|---|---|
| `app/config.py` | Toàn bộ cấu hình đọc từ biến môi trường: `PORT`, `ENVIRONMENT`, `LOG_LEVEL`, `AGENT_API_KEY`, `REDIS_URL`, `RATE_LIMIT_PER_MINUTE`, `DAILY_BUDGET_USD`, `MONTHLY_BUDGET_USD`. Có nạp `.env` khi chạy local nhưng không ghi đè biến đã có sẵn. **Fail fast**: thiếu `AGENT_API_KEY` thì app không khởi động. Không có secret mặc định nào trong code. |
| `app/redis_client.py` | `redis.from_url(...)` không kết nối lúc import, nên container vẫn khởi động được khi chưa có Redis. Timeout kết nối 1 giây để `/ready` và `/ask` trả lỗi nhanh thay vì treo. `redis_healthy()` dùng lệnh `PING`. |
| `app/auth.py` | Đọc header `X-API-Key` bằng `APIKeyHeader`. Thiếu hoặc sai key đều trả **401** (dùng `hmac.compare_digest` để tránh timing attack). Hàm `key_id()` băm SHA-256 key để dùng làm key Redis và ghi log, nên **không bao giờ lưu hay ghi log key gốc**. |
| `app/rate_limiter.py` | Sliding window log dùng Redis sorted set: `ZREMRANGEBYSCORE` → `ZCARD` → `ZADD` → `PEXPIRE`, gói trong **một script Lua chạy atomic**, nên 2 worker hay nhiều instance cùng gọi cũng không vượt giới hạn. Vượt giới hạn thì trả **429** kèm `Retry-After` và `X-RateLimit-*`. |
| `app/cost_guard.py` | Cộng dồn chi phí (tính theo token, giá gpt-4o-mini) bằng `INCRBYFLOAT` vào 2 key: `cost:<id>:d:<YYYY-MM-DD>` và `cost:<id>:m:<YYYY-MM>`, kèm `EXPIRE`. Ngày hoặc tháng mới thì dùng key mới, nên tự reset. `check_budget` chạy **trước** khi gọi LLM: vượt ngân sách ngày hoặc tháng thì trả **402**. `record_cost` chạy **sau** khi gọi LLM. |
| `app/main.py` | `/health` luôn trả 200 và không đụng tới Redis. `/ready` trả 503 khi Redis chết hoặc khi đang tắt (draining). `/ask` đi qua các bước: auth → rate limit → budget → LLM → ghi chi phí. Handler khai báo bằng `def` để chạy trong threadpool, tránh lỗi blocking event loop đã thấy ở Part 5. Log JSON qua `JsonFormatter`, mỗi request có `request_id`. Có handler lỗi riêng: 422 trả `{"error":"invalid_request","details":[...]}`, lỗi Redis trả **503** `service_unavailable`, lỗi khác trả 500 `internal_error`. **Không bao giờ trả stack trace cho client.** |
| `Dockerfile` | 2 stage, cùng base `python:3.11-slim`: stage builder tạo venv `/opt/venv`, stage runtime chỉ copy venv, `app/` và `utils/`. Chạy bằng user `agent` (không phải root). Có `HEALTHCHECK` gọi `/health`. `CMD ["sh","-c","exec uvicorn ... --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-2} --timeout-graceful-shutdown 8"]`: dùng `exec` để uvicorn là PID 1 (đã kiểm tra `/proc/1/cmdline`). |
| `docker-compose.yml` | Service `agent` build từ `Dockerfile`, đọc `.env` nếu có (`required: false`), có `REDIS_URL=redis://redis:6379/0`, `depends_on` redis với `condition: service_healthy`. Service `redis` dùng `redis:7-alpine` có healthcheck và volume AOF. |
| `.dockerignore` | Loại `.env`/`.env.*` (giữ lại `.env.example`), `__pycache__`, `venv`/`.venv`, `.git`, `*.md`, `benchmark-observability/`, script chấm. |
| `render.yaml` | Nền tảng chính là Render: web service `runtime: docker`, `rootDir: 06-lab-complete`, `healthCheckPath: /health`, `AGENT_API_KEY` khai báo `sync: false` (nhập trên dashboard). `REDIS_URL` lấy từ Render Key Value qua `fromService ... property: connectionString`. |
| `railway.toml` | Dự phòng: `builder = "DOCKERFILE"`, `healthcheckPath = "/health"`. |

### Kiểm thử thêm bằng `docker compose` (agent + Redis)

```text
health: 200  ready: {"ready":true}
no key: {"detail":"Missing API key. Send header: X-API-Key: <key>"} [401]
wrong key: {"detail":"Invalid API key."} [401]
ok: {"question":"What is deployment?","answer":"Deployment là quá trình đưa code từ máy bạn lên server để người khác dùng được.","model":"mock-llm","usage":{"input_tokens":6,"output_tokens":32,"cost_usd":2.01e-05,"rate_limit_remaining":9,"daily_spent_usd":2e-05,"daily_budget_remaining_usd":0.99998}} [200]
--- rate limit (RATE_LIMIT_PER_MINUTE=10, đã dùng 1)
200 200 200 200 200 200 200 200 200 429 429
HTTP/1.1 429 Too Many Requests
retry-after: 59
--- key trong Redis (không chứa API key gốc)
ratelimit:<key_id>
cost:<key_id>:d:2026-11-26
cost:<key_id>:m:2026-11
--- tắt Redis
health: 200  ready: {"ready":false,"reason":"redis_unavailable"} [503]
ask w/o redis: HTTP/1.1 503 Service Unavailable
{"error":"service_unavailable","detail":"State store unavailable, retry later."}
--- bật lại Redis
ready after redis back: {"ready":true}
--- container
user: agent
PID 1: /opt/venv/bin/python /opt/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2 --timeout-graceful-shutdown 8 --no-server-header
```

Kiểm tra xử lý input sai: mọi trường hợp đều trả 422 với body cùng một dạng và không có stack trace.

```text
{"question":""}    -> {"error":"invalid_request","details":[{"field":"question","msg":"String should have at least 1 character"}]} [422]
{"question":"   "} -> {"error":"invalid_request","details":[{"field":"question","msg":"Value error, must not be blank"}]} [422]
{bad               -> {"error":"invalid_request","details":[{"field":"body","msg":"JSON decode error"}]} [422]
{}                 -> {"error":"invalid_request","details":[{"field":"question","msg":"Field required"}]} [422]
question > 2000 ký tự -> [422]
```

Một dòng log mẫu (JSON, không chứa API key hay nội dung câu hỏi):

```json
{"ts": "2026-11-26T07:48:12.261+00:00", "lvl": "INFO", "logger": "agent", "event": "llm_call", "request_id": "a1586bcf5eda440f80e8952987b85039", "key_id": "8254c329a92850f6", "user_id": null, "question_chars": 2, "input_tokens": 2, "output_tokens": 26, "cost_usd": 1.59e-05, "llm_ms": 105.7}
```

### Các vấn đề gặp phải và cách xử lý

1. **Graceful shutdown bị treo.** Lần chạy đầu bị ❌ "process không thoát sau 20s".
   - Nguyên nhân: `uvicorn` 0.30 **import app bên trong `capture_signals()`** (`server.py`: `with self.capture_signals(): ... config.load()`). Mình đã gọi `signal.signal(SIGTERM, ...)` lúc import module, làm **đè mất handler của uvicorn**, nên uvicorn không bao giờ nhận được SIGTERM.
   - Cách sửa: chỉ cài handler trong `lifespan` startup, lúc handler của uvicorn đã có sẵn. Handler mới đặt `_draining = True` (để `/ready` trả 503), rồi **gọi lại handler cũ** của uvicorn.
   - Sau khi sửa: request đang chạy vẫn nhận 200, process thoát với exit code 0, `docker stop` mất 0.5 giây.
2. **Docker Hub trả 429 Too Many Requests** khi build (`HEAD .../python/manifests/3.11-slim`). Đây là giới hạn pull ẩn danh theo IP của mạng lab dùng chung.
   - Mình **không đổi Dockerfile**. Chỉ pull cùng image chính thức từ mirror `public.ecr.aws/docker/library/python:3.11-slim`, rồi `docker tag` thành `python:3.11-slim` ở máy local để BuildKit dùng bản có sẵn.
3. **Exit code khi chạy 1 worker ngoài Docker.** Với `--workers 1`, sau khi tắt xong uvicorn khôi phục handler mặc định rồi phát lại SIGTERM, nên process thoát với mã 143.
   - Trong container điều này không ảnh hưởng: uvicorn là PID 1, mà kernel bỏ qua signal không có handler gửi tới PID 1. Chế độ 2 worker (supervisor) thoát với mã 0.
   - Script chấm chạy `--workers 2` và `docker stop` đều ra exit code 0.

---

## AI log

| Part | Hỏi AI gì | Nhận được gì | Tự sửa / tự kiểm tra thế nào |
|---|---|---|---|
| Part 1 | Dùng Claude Code đọc `develop/app.py`, `production/app.py`, `config.py`, chạy hai bản và gọi các endpoint bằng `curl` | Danh sách anti-pattern kèm số dòng, output thật của các lệnh curl, bảng so sánh, và phát hiện bản production không nạp `.env` và không in log JSON | Đối chiếu từng số dòng với file gốc. Tự xem log server để xác nhận thiếu log JSON. Sửa `APP_NAME` trong `.env` rồi gọi `GET /` để xác nhận `.env` không được nạp. Gửi `kill -TERM` để xem trình tự shutdown. |
| Part 2 | Dùng Claude Code build 2 image, chạy container, đo kích thước, bật stack compose và test qua Nginx | Câu trả lời Ex 2.1, số đo kích thước image, sơ đồ kiến trúc, output curl qua Nginx | Số MB lấy trực tiếp từ `docker images` và `docker image inspect`. Build lại để xác nhận các layer được `CACHED`. `docker exec whoami` để xác nhận `root` và `appuser`. `docker network inspect` và lệnh PING Redis để xác nhận đường đi giữa các service. |
| Part 4 | Dùng Claude Code chạy bản develop và production của `04-api-gateway`, thử API key, JWT, rate limit, role; viết `check_budget` bằng Redis | Output 401/403/200/429, phân tích thuật toán rate limit, bản cài cost guard dùng Lua atomic | Gửi 20 request thật để thấy 429 ở request thứ 11. Decode payload JWT để kiểm tra `exp - iat = 3600`. Chạy test cost guard trên container Redis thật, gồm cả test race 100 request song song so với đáp án mẫu (66 so với 71 request được chấp nhận). |
| Part 5 | Dùng Claude Code chạy bản develop (health, ready, SIGTERM khi đang có request) và stack 3 instance, chạy `test_stateless.py`, kill một instance | Output health/ready, bằng chứng graceful shutdown, phân bổ round-robin, kết quả test stateless, phân tích lỗi event loop bị chặn và timeout 60 giây của Nginx | Đo thời gian thật bằng `curl -w %{time_total}`. Đếm request trong `docker compose logs`. Đối chiếu log Nginx `upstream timed out` với IP của instance đã tắt. Dùng override cổng 8081 vì cổng 8080 bị một container khác chiếm, không sửa file của đề. |
| Part 6 | Dùng Claude Code viết code cho các TODO trong `06-lab-complete/` (config, auth, rate limiter Redis + Lua, cost guard Redis, main.py, Dockerfile, compose, render.yaml, railway.toml), chạy script chấm tới khi PASS | Code hoàn chỉnh, PASS 12/12 (43/43 checks) | Đọc toàn bộ `check_production_ready.py` để hiểu tiêu chí, không sửa script. Lần đầu fail graceful shutdown: đọc `uvicorn/server.py` (`capture_signals`), tìm ra handler bị đè và sửa. Test thêm bằng `docker compose`: 401/200/429/422/503, tắt Redis thì `/ready` trả 503, kiểm tra PID 1 và user trong container. Chạy lại script đầy đủ sau mỗi lần sửa. |
