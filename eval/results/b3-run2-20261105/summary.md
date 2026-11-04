# B3 step load: per step (server side)

Last 300 s of each step. Latency is API Gateway's, for successful (2xx) requests, in ms. 429 = the gateway's deliberate rate cap; 5xx = errors (includes the API function hitting its reserved concurrency).

| Users | Window (UTC) | Requests/s | 2xx/s | P50 / P95 / P99 | 429 | 5xx | Lambda conc. max | Lambda throttles | Aurora ACU max | DB conn. max | DB CPU avg / max |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 17:58:17–18:03:17 | 0.4 | 0.4 | 38 / 1,883 / 1,915 | 0 | 0 | 1 | 0 | 0.50 | 1 | 14 / 19% |
| 10 | 18:04:17–18:09:17 | 3.6 | 3.6 | 38 / 2,401 / 2,599 | 0 | 0 | 9 | 0 | 4.00 | 9 | 15 / 28% |
| 50 | 18:10:18–18:15:18 | 18.0 | 18.0 | 34 / 2,392 / 2,574 | 0 | 0 | 28 | 0 | 4.00 | 28 | 19 / 70% |
| 100 | 18:16:17–18:21:17 | 36.7 | 36.7 | 32 / 2,365 / 2,546 | 0 | 0 | 48 | 0 | 4.00 | 48 | 23 / 72% |

P95 by endpoint (2xx only, ms; count in brackets):

| Users | `GET /recommendations` | `GET /recommendations/for-you` | `GET /jobs/{id}` | `PUT /jobs/{id}/review` | `GET /me` |
|---|---|---|---|---|---|
| 1 | 1,726 (32) | 1,919 (19) | 41 (20) | 49 (8) | 32 (3) |
| 10 | 2,326 (234) | 2,597 (227) | 34 (206) | 46 (153) | 32 (58) |
| 50 | 2,289 (1123) | 2,572 (1100) | 32 (1113) | 43 (662) | 32 (354) |
| 100 | 2,270 (2121) | 2,547 (2166) | 31 (2225) | 42 (1448) | 30 (765) |

Status counts per step: 1 users {'200': 109}; 10 users {'200': 1077}; 50 users {'200': 5389}; 100 users {'200': 11015}.
