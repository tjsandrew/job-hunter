# B3 step load: per step (server side)

Last 300 s of each step. Latency is API Gateway's, for successful (2xx) requests, in ms. 429 = the gateway's deliberate rate cap; 5xx = errors (includes the API function hitting its reserved concurrency).

| Users | Window (UTC) | Requests/s | 2xx/s | P50 / P95 / P99 | 429 | 5xx | Lambda conc. max | Lambda throttles | Aurora ACU max | DB conn. max | DB CPU avg / max |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 03:41:38–03:46:38 | 0.3 | 0.3 | 94 / 1,987 / 2,088 | 0 | 0 | 1 | 0 | 4.00 | 1 | 15 / 41% |
| 10 | 03:47:37–03:52:37 | 3.6 | 3.6 | 85 / 1,911 / 2,010 | 0 | 0 | 9 | 0 | 2.00 | 5 | 29 / 44% |
| 50 | 03:53:37–03:58:37 | 18.2 | 18.2 | 147 / 1,784 / 1,927 | 0 | 0 | 28 | 0 | 4.00 | 16 | 86 / 100% |
| 100 | 03:59:37–04:04:37 | 28.3 | 27.5 | 1,158 / 2,794 / 3,072 | 0 | 231 | 50 | 194 | 4.00 | 49 | 100 / 100% |

P95 by endpoint (2xx only, ms; count in brackets):

| Users | `GET /recommendations` | `GET /recommendations/for-you` | `GET /jobs/{id}` | `PUT /jobs/{id}/review` | `GET /me` |
|---|---|---|---|---|---|
| 1 | 1,805 (23) | 2,088 (23) | 83 (20) | 81 (7) | 66 (4) |
| 10 | 1,665 (234) | 2,010 (215) | 80 (258) | 87 (79) | 76 (69) |
| 50 | 1,600 (1180) | 1,925 (1120) | 184 (1223) | 204 (397) | 176 (367) |
| 100 | 2,424 (1795) | 3,070 (1763) | 1,196 (1776) | 1,270 (586) | 1,192 (559) |

Status counts per step: 1 users {'200': 101}; 10 users {'200': 1079}; 50 users {'200': 5463}; 100 users {'200': 8261, '503': 231}.
