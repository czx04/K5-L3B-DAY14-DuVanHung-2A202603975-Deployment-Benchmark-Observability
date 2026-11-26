# Benchmark & Observability Report — Day 14

> Mọi con số trong báo cáo đều lấy từ report JSON trong `reports/` (bản gốc ở `06-lab-complete/benchmark-observability/develop/reports/`) và CSV trong `benchmark-results/`. Không có số nào là ước lượng.

**Họ tên:** Du Van Hung (2A202603975)
**Ngày chạy:** 2026-11-26
**Môi trường:** MacBook Apple M1 (8 CPU, 16 GB RAM), macOS 26.3, Python 3.12.6 (venv), Docker Desktop 27.4.0. Load generator và agent chạy trên **cùng một máy**.

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < **500 ms** | Bình thường p95 của v2 khoảng 220–240 ms (mục 2), nên 500 ms để dư khoảng 2 lần cho jitter và retrieval mà người dùng vẫn thấy nhanh. Không đặt theo p99, vì mock cố ý có khoảng 3% request chậm thêm 1.5 giây. Nếu đặt theo p99 thì SLO luôn vỡ, và alert sẽ réo liên tục. |
| Error rate `/ask` | < **2 %** | Upstream LLM tự lỗi khoảng 1% (`MOCK_ERROR_RATE=0.01`). Ngưỡng 2% gấp đôi mức nền, tức error budget còn khoảng 1% cho sự cố của chính mình. Alert được đặt lỏng hơn (5% trong 1 phút) để không báo động vì một đợt lỗi ngắn. |
| Accuracy trên golden dataset | ≥ **85 %** (gate trong CI), mục tiêu 100 % | v2 ban đầu đạt 91.3%. Đặt gate 85% chặn được việc tụt 2 câu trở lên. Gate còn **cấm regression** so với baseline, nên dù accuracy chưa xuống dưới 85% mà một câu trước đây đúng nay sai thì vẫn bị chặn. |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

Lệnh chạy: `python load_test.py --url http://localhost:8002 --requests 300 --concurrency <c> --out reports/load_v2_c<c>.json`, với `MOCK_SLOW_RATE=0.03` mặc định.

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.15 | 195.2 | 225.1 | 1704.6 | 1.00% (3×503) | ✅ PASS |
| 10 | 35.75 | 195.0 | 230.1 | 1705.2 | 1.00% (3×503) | ✅ PASS |
| 50 | 111.72 | 197.2 | 241.6 | 1715.2 | 0.67% (2×503) | ✅ PASS |
| 100 | 48.60 | 622.6 | 3978.3 | 4339.5 | 0.67% (2×503) | ❌ FAIL (p95) |

File: `reports/load_v2_c1.json`, `load_v2_c10.json`, `load_v2_c50.json`, `load_v2_c100.json`.

**Nhận xét:** RPS tăng **gần tuyến tính** từ c=1 lên c=10 (4.15 → 35.75, gấp 8.6 lần với 10 lần concurrency), **dưới tuyến tính** ở c=50 (111.72, gấp 27 lần), rồi **sụt** ở c=100 (48.60).

- **c=1 đến c=50: p50 gần như không đổi (195 → 197 ms).** Agent chạy bất đồng bộ (`asyncio.sleep` mô phỏng chờ LLM), nên phần lớn thời gian chỉ là chờ I/O. Thêm request đồng thời không làm request khác chậm đi, nên theo định luật Little ta có RPS ≈ concurrency / latency. Với c=10: 10 / 0.245 s ≈ 41 RPS, khớp với 35.75 đo được.
- **c=50 dưới tuyến tính** là do phương pháp đo. 300 request chia cho 50 worker thì mỗi worker chỉ gửi khoảng 6 request, và tổng thời gian chạy (2.69 s) bị **kéo dài bởi vài request chậm 1.7 giây** của tail latency. Chạy càng ngắn thì phần đuôi chiếm tỉ trọng thời gian càng lớn, nên RPS bị đo thấp hơn thực tế.
- **c=100 sụt** là do **nghẽn ở phía kết nối, không phải ở agent**. Mình đối chiếu log JSON phía server của chính lần chạy c=100: thời gian xử lý `/ask` trong agent vẫn là **p50 199.4 ms, p95 234.0 ms** (`llm_ms` p95 192.7 ms), trong khi client đo được p95 3978 ms. Như vậy khoảng 3.7 giây nằm *trước khi request vào tới handler*.
  - `load_test.py` mở 100 kết nối TCP mới cùng lúc (`httpx.Limits(max_connections=100)`), tới một tiến trình uvicorn duy nhất chạy trên một event loop.
  - Hàng đợi accept của macOS bị giới hạn bởi `kern.ipc.somaxconn = 128`, và load generator lại chạy chung máy với agent.
  - Các kết nối phải xếp hàng hoặc thử SYN lại (theo backoff khoảng 1 s, 2 s...), khớp với p90 khoảng 3.3 s và max khoảng 5.4 s.
  - Cách khắc phục: chạy nhiều worker hoặc nhiều instance sau load balancer (mục 5), dùng connection pool hoặc keep-alive và warm-up kết nối, đặt load generator trên máy khác, hoặc giới hạn concurrency ở phía client hay gateway.
- Error rate không phụ thuộc tải (0.67–1%). Toàn bộ là `503` do mock LLM tự lỗi khoảng 1%, không có lỗi do quá tải.

### 2.2 Tail latency

Lệnh chạy: khởi động lại v2 với `MOCK_SLOW_RATE=<x>`, rồi `python load_test.py --url http://localhost:8002 --requests 300 --concurrency 20 --out reports/load_v2_slow_<x>.json`.

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) | RPS | SLO p95 ≤ 500 ms |
|---|---|---|---|---|---|
| 0 | 190.5 | 218.0 | 229.3 | 101.57 | ✅ |
| 0.03 (mặc định) | 241.0 | 231.2 | 1700.2 | 73.46 | ✅ |
| 0.1 | 349.5 | 1687.7 | 1712.2 | 46.72 | ❌ |

File: `reports/load_v2_slow_0.json`, `load_v2_slow_0.03.json`, `load_v2_slow_0.1.json`.

**Nhận xét:**
- **p99 nhạy nhất.** Chỉ cần 3% request chậm là **p99 nhảy từ 229 lên 1700 ms (gấp 7.4 lần)**, trong khi avg chỉ tăng 50 ms (190.5 → 241.0) và p95 gần như không đổi (218 → 231). Lý do: 3% < 5%, nên các request chậm nằm hết phía trên ngưỡng p95, nhưng lọt vào 1% cao nhất mà p99 đo.
- **Ở 10%** (vượt 5%), các request chậm tràn xuống cả vùng p95: **p95 lên 1688 ms (gấp 7.7 lần) và SLO vỡ**, trong khi avg mới tăng **159 ms** (190.5 → 349.5), một con số trông vẫn "chấp nhận được".
- **Vì sao không đặt SLO theo average:** average gộp tất cả mọi người thành một con số. 10% người dùng phải chờ 1.7 giây vẫn chỉ làm average tăng khoảng 160 ms. Một SLO "avg < 500 ms" vẫn PASS ở cả 3 dòng trên, kể cả khi 1/10 người dùng có trải nghiệm tệ. Percentile trả lời đúng câu hỏi người dùng quan tâm: "*95% (hay 99%) người dùng chờ tối đa bao lâu?*", nên phát hiện được nhóm bị chậm. Ngoài ra RPS cũng giảm (101 → 47), vì mỗi worker bị giữ lại lâu hơn bởi request chậm.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3% (1/23) | 91.3% (21/23) | **100% (23/23)** |
| Avg tokens / câu | 57.0 | 109.0 | 116.3 |
| Tổng cost (USD) | 0.000403 | 0.000760 | 0.000813 |
| Cost / câu đúng (USD) | 0.00040335 | 0.00003619 | 0.00003537 |
| Latency p50 / p95 (ms) | 161.7 / 191.1 | 195.4 / 216.2 | 187.7 / 220.8 |
| Quality gate | ❌ FAIL (exit 1) | ✅ PASS (≥ 80%, 0 regression so với v1) | ✅ PASS (`--min-accuracy 1.0`, 0 regression so với v2) |

File: `reports/eval_v1.json`, `reports/eval_v2.json` (`--baseline reports/eval_v1.json`), `reports/eval_v2_fixed.json` (`--baseline reports/eval_v2.json --min-accuracy 1.0`).

**Những câu v2 trả lời sai ban đầu và cách sửa:**

| ID | Keyword bị thiếu | Đã sửa gì |
|---|---|---|
| `scaling-03` "Kubernetes HPA scale dựa trên những chỉ số nào?" | `cpu`, `memory`, `custom metrics` | Thêm entry vào `KNOWLEDGE_BASE` với trigger `["hpa", "kubernetes", "autoscal"]`: *"Kubernetes HPA (Horizontal Pod Autoscaler) tự tăng/giảm số pod dựa trên CPU, memory hoặc custom metrics như RPS hay độ dài hàng đợi…"* |
| `security-02` "JWT khác gì API key trong xác thực?" | `token`, `hết hạn`, `chữ ký` | Thêm entry với trigger `["jwt"]`: *"API key là chuỗi bí mật cố định, không tự hết hạn… JWT là token có chữ ký số, chứa thông tin user và thời điểm hết hạn (exp); server chỉ cần xác minh chữ ký…"* |

- Nguyên nhân: retrieval không tìm được tài liệu nào (không có trigger khớp), nên v2 rơi về câu trả lời chung chung (score 0.0).
- **Tránh regression:** mình grep toàn bộ `golden_dataset.jsonl` và xác nhận mỗi trigger mới (`jwt`, `kubernetes`, `hpa`, `autoscal`) chỉ xuất hiện trong đúng câu cần sửa. Không dùng trigger rộng như `scale` hay `token`, vì `scaling-01` ("scale ngang") và `cost-01` sẽ bị kéo sang tài liệu mới và trả lời sai. Kết quả: `Câu được cải thiện: 2`, `Câu bị regression: 0`.
- Đã chép phần sửa sang `production/utils/mock_llm.py` để stack Docker ở CP8 cũng đạt 100%. Lệnh `diff` hai `KNOWLEDGE_BASE` không ra khác biệt nào.

**Quality gate trong CI:** file [`.github/workflows/eval.yml`](.github/workflows/eval.yml)
- Workflow chạy trên mỗi pull request có đụng tới `benchmark-observability/`. Nó khởi động agent v2 với `MOCK_ERROR_RATE=0 MOCK_SLOW_RATE=0` để eval không bị flaky, rồi chạy `python eval/run_eval.py --min-accuracy 0.85 --baseline reports/eval_v2_fixed.json`.
- `run_eval.py` thoát với **exit code 1** khi accuracy < ngưỡng *hoặc* có câu bị regression. Step fail thì job fail, và khi bật "Require status checks to pass" cho nhánh `main` thì **PR không merge được**.
- Kiểm chứng: chạy eval v1 với `--baseline reports/eval_v2.json` cho ra `Câu bị regression : 20`, `Quality gate ... ❌ FAIL`, `exit=1`. Chạy đúng lệnh của CI trên v2 đã sửa (ở local) cho ra `✅ PASS`, `exit=0`.

**Trade-off chất lượng / chi phí / latency giữa v1 và v2:**
- **Chất lượng:** v2 có retrieval (RAG) nên accuracy tăng từ 4.3% lên 91.3%, và 100% sau khi bổ sung tài liệu.
- **Chi phí mỗi câu:** prompt chứa thêm tài liệu nên **token mỗi câu gần gấp đôi** (57 → 109) và tổng cost gần gấp đôi (0.000403 → 0.000760 USD).
- **Chi phí mỗi câu đúng:** v1 tốn 0.00040335 USD mỗi câu đúng, v2 chỉ 0.00003619 USD, **rẻ hơn 11.1 lần**. Vì v1 gần như luôn sai, tiền bỏ ra cho v1 hầu hết là lãng phí. "Cost / câu đúng" là thước đo công bằng hơn "cost / câu" khi so sánh hai phiên bản có chất lượng khác nhau.
- **Latency:** p95 tăng khoảng 25 ms (191 → 216), do bước retrieval khoảng 20 ms cộng với prompt dài hơn (latency mock phụ thuộc số input token). Mức này vẫn nằm xa dưới SLO 500 ms.
- **Kết luận:** đổi khoảng 2 lần token và khoảng 25 ms lấy +87 điểm accuracy là **rất đáng**. Bản sửa KB tăng thêm 7.3 token/câu (do tài liệu mới dài hơn), nhưng cost/câu đúng còn giảm tiếp (0.00003619 → 0.00003537).

### Exercise 7.1: Metrics của agent

Chạy `curl -s http://localhost:8002/metrics | grep -v "^#"` sau một request `/ask`:

| Loại | Ví dụ trong output | Ý nghĩa |
|---|---|---|
| **Counter** (chỉ tăng) | `http_requests_total{method="POST",route="/ask",status="200"} 1.0`, `llm_tokens_total{model="mock-llm-small",type="input"} 91.0`, `llm_cost_usd_total{model="mock-llm-small"} 4.665e-05` | Dùng với `rate()` để ra req/s, tokens/s, USD/giờ |
| **Gauge** (lên xuống) | `agent_in_flight_requests 0.0`, `agent_info{model="mock-llm-small",version="v2"} 1.0` | Saturation hiện tại; metadata phiên bản |
| **Histogram** | `llm_request_duration_seconds_bucket{le="0.2",model="mock-llm-small"} 1.0` cùng `_count` và `_sum` | Tính percentile bằng `histogram_quantile()` |

**Nếu dùng URL thật làm label `route`:** mỗi URL lạ mà bot quét (`/wp-admin`, `/.env`, `/a1b2c3`...) sẽ tạo **một tổ hợp label mới**, tức thêm một time series cho counter và **thêm 13 series** cho histogram (11 bucket, `+Inf`, `_count`, `_sum`). Hàng nghìn URL ngẫu nhiên sẽ sinh ra hàng chục nghìn series. Prometheus tốn RAM và chậm dần cho tới khi hết bộ nhớ (cardinality explosion), và kẻ tấn công có thể cố ý làm vậy để đánh sập hệ thống giám sát. Dùng `route.path` (template) thì mọi URL không khớp đều gom vào `route="unmatched"`. Đã kiểm chứng: gọi `/wp-admin`, `/.env`, `/a1b2c3` chỉ ra **một** series `http_requests_total{method="GET",route="unmatched",status="404"} 3.0`.

**Metric mới `agent_question_length_chars`** (đã thêm vào `develop/app.py`): `Histogram` với bucket `(20, 50, 100, 200, 500, 1000, 2000)`, được `observe(len(body.question))` ở đầu `/ask`. Kết quả sau câu hỏi dài 40 ký tự: `agent_question_length_chars_count 1.0`, `agent_question_length_chars_sum 40.0`, `agent_question_length_chars_bucket{le="50.0"} 1.0`. Dùng Histogram chứ không dùng label `length=...`, vì độ dài có vô số giá trị.

---

## 4. Observability stack (production)

Stack được bật bằng `docker compose -p k5-day14-observability ...` trong `06-lab-complete/benchmark-observability/production/`. Thời gian ghi theo UTC, ngày 2026-11-26.

**Ba chỗ chạy khác với đề (đều có lý do, không sửa file cấu hình gốc của đề):**
1. **Cổng 8080 bị chiếm** bởi container của một project khác trên máy. Mình dùng thêm một file override chỉ để đổi cổng host của Nginx sang **8081** (`ports: !override ["8081:80"]`). Bên trong mạng Docker, Locust vẫn gọi `http://nginx` như đề yêu cầu.
2. **Docker Hub trả 429 (giới hạn pull ẩn danh)** khi pull `locustio/locust:2.47.0`. Mình build một image thay thế ở local, cùng tag và cùng phiên bản: `python:3.11-slim` + `pip install locust==2.47.0`, `ENTRYPOINT ["locust"]`. Các lệnh `docker compose run ... locust ...` giữ nguyên.
3. **Sửa lỗi trong `production/Dockerfile`:** agent crash với lỗi `ModuleNotFoundError: No module named 'uvicorn'`. Nguyên nhân: `useradd -d /app` đặt HOME của user `agent` là `/app`, nên Python tìm user site-packages ở `/app/.local`, trong khi gói được cài vào `/home/agent/.local`. Mình thêm `ENV PYTHONUSERBASE=/home/agent/.local` (giống Dockerfile ở Part 5) và agent khởi động được.

Kiểm tra ban đầu:
- `POST /ask` qua Nginx trả 200, kèm header `x-trace-id` và `X-Served-By`. Thiếu `X-API-Key` thì trả 401.
- Prometheus thấy target `agent` ở trạng thái `up`.
- `promtool test rules alert_rules_test.yml` trả về `SUCCESS`.

### 4.1 Screenshot

- [x] [Dashboard Grafana khi đang có tải](screenshots/grafana-dashboard.png): chụp lúc 08:32:39 UTC, khi 3 instance đang chịu 100 user.
- [x] [Trace chậm trong Jaeger](screenshots/jaeger-slow-trace.png): span `chat mock-llm-small` chiếm 1.9 s trên tổng 2.1 s.
- [x] [Trace lỗi trong Jaeger](screenshots/jaeger-error-trace.png): status `503`, span `chat mock-llm-small` có `error.type=upstream_unavailable` và event `exception`.
- [x] [Trang Alerts của Prometheus](screenshots/prometheus-alert-firing.png): nhóm `agent-slo` hiện **FIRING (2)**, gồm `AgentHighErrorRate` và `AgentInstanceDown`, chụp lúc 08:42:51 UTC.

**Exercise 7.4: đọc dashboard.** Số liệu lấy bằng PromQL lúc 08:32:39 UTC, 3 instance, 100 user:

| Câu hỏi | Trả lời |
|---|---|
| p95 và avg | **p95 = 299 ms, avg = 241 ms**. Panel latency cho thấy p50 khoảng 200 ms, nhưng **p99 khoảng 1.7–1.9 s** (đường xanh trên cùng, nằm hẳn trong vùng đỏ > 1 s). Khoảng cách avg ↔ p95 khá nhỏ (khoảng 58 ms), còn khoảng cách tới p99 rất lớn. Lý do: khoảng 3% request bị mock làm chậm thêm 1.5 s (`MOCK_SLOW_RATE=0.03`). Vì 3% < 5%, các request này nằm trên ngưỡng p95, nhưng kéo p99 và cả avg lên. Average che mất nhóm người dùng phải chờ gần 2 giây; tail latency chỉ hiện ra ở p99. |
| Nginx có chia đều traffic không? | **Có.** Panel "Requests/s theo instance" ra 172.29.0.4 = 20.29, 172.29.0.7 = 20.45, 172.29.0.8 = 20.33 req/s (tổng 61.07). Nginx dùng round-robin, kết hợp `server agent:8000 resolve` nên tự thấy instance mới khi scale. |
| Vì sao input tokens/s > output tokens/s? | Input khoảng **4749 tokens/s**, output khoảng **2519 tokens/s** (tỉ lệ 1.9:1). Agent v2 nhét system prompt và **tài liệu retrieve được (context RAG)** vào prompt, cộng thêm câu hỏi. Còn câu trả lời của mock chỉ là một đoạn tài liệu ngắn. Đây cũng là lý do v2 tốn token gấp đôi v1 (mục 3). Ngoài đời giá output thường đắt hơn input (ở đây 4 lần), nên cost không tỉ lệ thuận với tổng token. |
| `curl http://localhost:8081/metrics` | Trả **`404 Not Found`**, vì `nginx.conf` có `location = /metrics { return 404; }`. `/metrics` để lộ thông tin nội bộ (route, lưu lượng, lỗi, version, chi phí), và ai cũng có thể gọi liên tục để tốn tài nguyên. Chỉ Prometheus được scrape trực tiếp từng container qua mạng nội bộ `obs_net` (DNS service discovery `agent:8000`), không đi qua Nginx. |

### 4.2 Thí nghiệm "phá hệ thống"

Trong suốt các thí nghiệm, Locust chạy 30 user (`-u 30 -r 5`) và tạo khoảng **18.8 req/s** vào `/ask`. Mỗi thay đổi được áp dụng bằng cách sửa `.env` rồi `docker compose up -d --scale agent=2 agent` (riêng D dùng `docker pause`). Thời gian tới firing được đo bằng một script poll API `/api/v1/rules` mỗi 2 giây, tính từ lúc đổi cấu hình.

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` (08:39:46) | `AgentHighErrorRate` (critical) | pending sau 28.3 s, **firing sau 86.5 s** (08:41:12). Error rate đo được 20.6% | *Error rate* chuyển đỏ, *Requests/s theo status code* (503 tăng), *LLM calls theo kết quả* (error tăng) |
| B | `MOCK_SLOW_RATE=0.3` (08:43:55) | `AgentHighLatencyP95` (warning) | pending sau 23.7 s, **firing sau 144.2 s** (08:46:19). p95 = 1.92 s, p99 = 1.98 s, trong khi **avg = 0.67 s, p50 = 0.235 s** | *Latency p50/p95/p99*: p95 nhảy vào vùng đỏ, p50 gần như không đổi |
| C | `LLM_MODEL=mock-llm-large` (08:47:30) | `LLMCostBurnRateHigh` (warning) | pending sau 23.8 s, **firing sau 144.4 s** (08:49:54). Cost theo cửa sổ 1m: **$33.9/giờ** (trước đó khoảng $1.8–2.4/giờ), p95 lên 0.71 s | *Cost burn rate (USD/giờ)*, *LLM latency p95 theo model*, bảng *Phiên bản đang chạy* đổi sang `mock-llm-large` |
| D | `docker pause k5-day14-observability-agent-1` (08:41:21) | `AgentInstanceDown` (critical, `instance=172.29.0.4:8000`) | pending sau 12.4 s, **firing sau 42.6 s** (08:42:03) | *Instances up* giảm từ 2 xuống 1, *Requests/s theo instance* (một đường về 0). Panel *Error rate* **không** phản ánh: Nginx log có **31 lỗi 504**, nhưng `http_requests_total{status="504"}` của agent bằng 0 |
| E | `AGENT_VERSION=v1` (08:58:03) | **Không có** (quan sát 3 phút: cả 4 rule `inactive`) | — | *Retrieval hit ratio* mất (v2 trước đó có 18.45 hit/s, v1 thì `agent_retrieval_total` không còn dữ liệu), *Tokens/s* giảm một nửa (input 1420 → 675/s), bảng version đổi `v2` → `v1`. **p95 còn tốt hơn** (296 → 199 ms), cost giảm từ $2.39 xuống $1.16/giờ |

Ghi chú:
- **Thời gian tới firing** ≈ thời gian để rate trong cửa sổ `[1m]` hoặc `[5m]` vượt ngưỡng (khoảng 12–28 giây, cộng 10 giây chờ Prometheus phát hiện container mới qua DNS) + thời gian `for` của rule (A: 1m, B và C: 2m, D: 30s). Nhờ `for`, một spike ngắn không gây báo động giả, đổi lại là phát hiện chậm hơn.
- **Ngưỡng cost đang quá chặt so với tải.** Với model nhỏ ở 30 user (khoảng 18.8 req/s), chi phí đã là **$2.39/giờ**, vượt ngưỡng $2/giờ. Sau thí nghiệm C, `LLMCostBurnRateHigh` **không tự tắt** dù đã trả về `mock-llm-small` (08:57:50 vẫn firing, cost theo cửa sổ 5m là $2.40/giờ), và chỉ tắt khi chuyển sang v1 (ít token hơn). Nên đặt ngưỡng theo ngân sách thật và theo lưu lượng dự kiến (ví dụ cost cho mỗi request, hoặc ngân sách theo ngày), không dùng một con số tuyệt đối cố định.
- **D, vì sao dùng `pause` chứ không dùng `stop`:** container bị pause vẫn còn trong Docker DNS nhưng không trả lời, nên `up == 0` và alert bắn. Nếu `stop`, container biến mất khỏi DNS, Prometheus coi như target không tồn tại, nên không có alert.
- **D, vì sao lỗi 504 không hiện trên dashboard:** lỗi 504 sinh ra ở Nginx (`proxy_read_timeout 10s` hết hạn khi instance bị treo). Request đó chưa bao giờ được agent xử lý xong, nên metric của agent không đếm. Metric chỉ phản ánh những gì *chính service đó* nhìn thấy. Production cần giám sát thêm ở tầng load balancer (log hoặc metric của Nginx/ingress) và synthetic check từ bên ngoài.

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**
- Đây là sự cố **chất lượng**, không phải sự cố **hạ tầng**. v1 nhanh hơn, rẻ hơn, không lỗi, nên mọi Golden Signal đều xanh, trong khi accuracy rơi từ 100% xuống 4.3% (mục 3).
- Cách phát hiện:
  1. **Chặn trước khi deploy:** quality gate eval trong CI (`run_eval.py --min-accuracy ... --baseline ...`, đã viết ở `.github/workflows/eval.yml`). Bản v1 sẽ bị chặn với exit code 1 và 20 câu regression.
  2. **Giám sát chất lượng khi đang chạy:**
     - Chạy eval định kỳ (canary hoặc synthetic) trên golden dataset vào production, rồi đẩy `eval_accuracy` thành metric và đặt alert.
     - Theo dõi các proxy metric: retrieval hit ratio giảm về 0, tokens/request giảm đột ngột, độ dài câu trả lời, tỉ lệ câu trả lời "chung chung".
     - Alert khi version đang chạy khác với version đã qua eval.
  3. **Tín hiệu từ người dùng:** nút 👍/👎, tỉ lệ hỏi lại, và LLM-as-judge chấm trên một mẫu traffic thật.

### 4.3 Debug bằng trace

Trace chậm nhất trong số các trace của instance còn chạy. Mình tìm bằng Jaeger API v3 (`duration_min=1500ms`), có 704 trace ≥ 1.5 s trong 1 giờ. Ảnh: [screenshots/jaeger-slow-trace.png](screenshots/jaeger-slow-trace.png).

- `trace_id`: `f96106e68d833e5c9c342a65a9b10dc7` (instance `a27a690295ad`, 2026-11-26 08:27:37 UTC)
- Tổng thời gian: **2083.9 ms** (`POST /ask`)
- Span chiếm nhiều thời gian nhất: **`chat mock-llm-small`, 1947.5 ms, 93.5%** tổng thời gian (`gen_ai.request.model=mock-llm-small`, `gen_ai.usage.input_tokens=78`, `output_tokens=41`)
  - `agent.run`: 1963.4 ms (94.2%)
  - `agent.retrieve_context`: 15.7 ms (0.8%)
- **Kết luận:** chậm do **upstream LLM**, không phải do code retrieval hay agent. Đây là một request rơi vào nhóm "slow" của mock. Log ghi `llm_ms = 1688.7` (latency mock định ra), còn span đo được 1947.5 ms. Phần chênh khoảng 259 ms là thời gian chờ event loop: lúc đó có 100 user, mỗi container bị giới hạn `cpus: 0.5`.
- Dòng log tương ứng (`docker compose logs agent | grep f96106e68d833e5c9c342a65a9b10dc7`):

```json
{"ts": "2026-11-26T08:27:39.124449+00:00", "level": "INFO", "service": "observable-agent", "instance": "a27a690295ad", "event": "llm_call", "trace_id": "f96106e68d833e5c9c342a65a9b10dc7", "span_id": "a2dbc30ff35c631b", "request_id": "57d7f2101a9a", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 78, "output_tokens": 41, "cost_usd": 3.6e-05, "llm_ms": 1688.7}
{"ts": "2026-11-26T08:27:39.126637+00:00", "level": "INFO", "service": "observable-agent", "instance": "a27a690295ad", "event": "http_request", "trace_id": "f96106e68d833e5c9c342a65a9b10dc7", "span_id": "a2dbc30ff35c631b", "request_id": "57d7f2101a9a", "method": "POST", "route": "/ask", "status": 200, "ms": 1966.3}
```

**Trace lỗi.** Ảnh: [screenshots/jaeger-error-trace.png](screenshots/jaeger-error-trace.png).
- `trace_id` `11f64c28cb40f8e1566a32d88bac6dd9`, tổng 95.0 ms, `POST /ask` trả **503**.
- Span `chat mock-llm-small` (75.1 ms) có `error.type=upstream_unavailable` và event `exception` với `exception.type=utils.mock_llm.LLMError`, `exception.message="Upstream LLM error: 503 Service Unavailable (mock)"`.
- Log tương ứng:

```json
{"ts": "2026-11-26T08:32:45.983713+00:00", "level": "INFO", "service": "observable-agent", "instance": "a27a690295ad", "event": "llm_error", "trace_id": "11f64c28cb40f8e1566a32d88bac6dd9", "span_id": "8a6305a4b080735f", "request_id": "13ec279717ff", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
```

Ghi chú: trace chậm nhất tuyệt đối là `81d574be20cc9b14a4419f0ab8a8b7b2` (2380.5 ms, span `chat mock-llm-small` 1639.3 ms). Trace này thuộc một container đã bị xoá khi scale xuống, nên không còn log để đối chiếu. Mình chọn trace ở trên để có cặp trace ↔ log đầy đủ.

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

Lệnh chạy: `docker compose -p k5-day14-observability run --rm --no-deps locust -f /mnt/locust/locustfile.py --host http://nginx --headless -u 100 -r 10 -t 2m --csv /mnt/results/scale_<n>`. Số liệu lấy từ dòng `/ask` trong `benchmark-results/scale_1_stats.csv` và `scale_3_stats.csv`.

| Số instance | RPS (`/ask`) | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 59.60 | 200 | 250 | 1700 | 70 / 7115 (0.98%, đều là 503 của mock) |
| 3 | 59.37 | 200 | 290 | 1700 | 64 / 7091 (0.90%, đều là 503 của mock) |

(Tính cả `/health`, dòng Aggregated: 65.52 và 65.45 req/s.)

> **Lưu ý về phương pháp:** lần chạy đầu tiên dùng đúng lệnh trong CHECKPOINTS (không có `--no-deps`) và bị **sai số instance**. `docker compose run locust` khởi động lại các service phụ thuộc (nginx → agent) theo `deploy.replicas: 2` mặc định.
> - Lần "1 instance" thực tế chạy với 2 agent: `agent-2` được tạo đúng lúc Locust bắt đầu (15:24:53 giờ local). Panel Requests/s theo instance cho thấy 2 đường, mỗi đường khoảng 30 req/s.
> - Lần "3 instance" bị compose thu về 2 agent.
>
> Mình xoá kết quả đó và chạy lại với `--no-deps`. Trước mỗi lần chạy, mình kiểm tra Prometheus có đúng 1 hoặc 3 target `up`, và `X-Served-By` trả về đúng 1 hoặc 3 IP khác nhau. Sau lần chạy thì kiểm tra lại số container. CSV trong `benchmark-results/` là của lần chạy đúng.

**Giải thích kết quả:** scale từ 1 lên 3 instance **không cải thiện** RPS (59.60 → 59.37) và p95 (250 → 290 ms, nằm trong sai số đo, vì Locust làm tròn percentile tới 2 chữ số có nghĩa). Nút thắt **không nằm ở agent**:

1. **Tải bị giới hạn bởi người dùng mô phỏng, không phải bởi server.** Mỗi user Locust nghỉ `between(0.5, 2)` giây (trung bình 1.25 s) giữa hai request. Với thời gian phản hồi khoảng 0.24 s, 100 user chỉ tạo được tối đa khoảng 100 / (1.25 + 0.24) ≈ **67 req/s**, khớp với 65.5 req/s đo được. Một instance đã phục vụ hết lượng tải này, thêm instance không có thêm request để xử lý.
2. **Latency do LLM quyết định.** Agent chạy bất đồng bộ (`asyncio`), chủ yếu chờ I/O tới LLM (mock `sleep` khoảng 120–180 ms, và 1.5 s với 3% request). Panel *LLM latency p95* đứng yên khoảng 198 ms ở cả hai lần chạy. Thêm instance không làm LLM trả lời nhanh hơn, nên p50 vẫn 200 ms, p99 vẫn 1700 ms (tail latency của upstream).
3. Chi phí cũng không đổi theo số instance, vì cost tính theo token chứ không theo số máy.

Scale ngang chỉ có ích khi một instance **bão hoà** (CPU, event loop, connection), ví dụ khi tăng số user hoặc giảm thời gian nghỉ, hoặc khi cần **sẵn sàng cao** (thí nghiệm D: còn instance khác gánh traffic). Ở mức tải này, giảm latency phải xử lý ở LLM: model nhanh hơn, cache câu trả lời, streaming, timeout hoặc hedged request để cắt phần tail.

---

## 6. Kết luận

- 3 điều học được về benchmark & observability:
  1. **Average nói dối, percentile thì không.** Ở mục 2.2, thêm 10% request chậm chỉ làm avg tăng 159 ms nhưng p95 tăng gấp 7.7 lần. Ở thí nghiệm B, avg 0.67 s trông "tạm ổn" trong khi p95 là 1.92 s. SLO và alert phải đặt theo p95/p99.
  2. **Số đo chỉ đúng khi biết chắc mình đang đo cái gì.** Hai lần mình suýt rút ra kết luận sai: c=100 trông như agent chậm, nhưng log phía server cho thấy agent vẫn ở p95 234 ms, nghẽn thật nằm ở tầng kết nối TCP. Còn benchmark scale lúc đầu chạy sai số instance mà không có lỗi nào báo. Luôn đối chiếu nhiều nguồn: client, log phía server, metric, và trạng thái hạ tầng.
  3. **Observability hạ tầng không thấy lỗi chất lượng.** Đổi sang v1 làm accuracy giảm từ 100% xuống 4%, nhưng dashboard xanh hơn (nhanh hơn, rẻ hơn) và không alert nào kêu. Cần eval trong CI kèm quality gate, và giám sát chất lượng liên tục. Tương tự, lỗi 504 ở Nginx không hiện trên metric của agent, nên cần quan sát ở nhiều tầng.
- Nếu đưa agent này lên production thật, mình sẽ thêm metric và alert sau:
  - **Chất lượng:** gauge `eval_accuracy` từ eval định kỳ hoặc canary, kèm alert khi tụt dưới ngưỡng. Retrieval hit ratio, alert khi giảm đột ngột. Tỉ lệ 👎 từ người dùng.
  - **Tầng biên:** metric của Nginx/ingress (tỉ lệ 5xx/504 ở load balancer) và synthetic check từ bên ngoài, gọi `/ask` thật mỗi phút qua URL public.
  - **SLO theo burn rate** (multi-window, ví dụ 5m và 1h) thay cho ngưỡng tức thời. Alert p99 riêng cho tail latency.
  - **Chi phí:** budget theo ngày hoặc tháng, cost/request, alert khi `LLM_MODEL` hoặc version thay đổi (annotation trên dashboard), và ngưỡng cost tính theo lưu lượng dự kiến thay vì con số tuyệt đối.
  - **Saturation:** độ trễ event loop, CPU/memory theo container, kèm alert khi in-flight requests vượt ngưỡng (để biết khi nào thật sự cần scale).
