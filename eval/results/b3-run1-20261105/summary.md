# B3 step load: per step (server side)

Last 300 s of each step. Latency is API Gateway's, for successful (2xx) requests, in ms. 429 = the gateway's deliberate rate cap; 5xx = errors (includes the API function hitting its reserved concurrency).

| Users | Window (UTC) | Requests/s | 2xx/s | P50 / P95 / P99 | 429 | 5xx | Lambda conc. max | Lambda throttles | Aurora ACU max | DB conn. max | DB CPU avg / max |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 17:28:31–17:33:31 | 0.3 | 0.3 | 1,810 / 2,240 / 2,297 | 0 | 0 | 1 | 0 | 0.50 | 1 | 55 / 78% |
| 10 | 17:34:31–17:39:31 | 3.6 | 3.6 | 32 / 2,377 / 2,586 | 0 | 0 | 9 | 0 | 1.00 | 9 | 60 / 100% |
| 50 | 17:40:30–17:45:30 | 21.7 | 10.5 | 31 / 2,389 / 2,548 | 515 | 2836 | 10 | 2,306 | 1.00 | 10 | 64 / 100% |
| 100 | 17:46:31–17:51:31 | 48.7 | 9.7 | 31 / 2,386 / 2,540 | 8602 | 3102 | 10 | 2,444 | 1.00 | 10 | 65 / 100% |

P95 by endpoint (2xx only, ms; count in brackets):

| Users | `GET /recommendations` | `GET /recommendations/for-you` | `GET /jobs/{id}` | `PUT /jobs/{id}/review` | `GET /me` |
|---|---|---|---|---|---|
| 1 | 2,010 (27) | 2,282 (22) | 48 (23) | 56 (4) | 41 (8) |
| 10 | 2,275 (204) | 2,586 (212) | 33 (217) | 42 (166) | 35 (72) |
| 50 | 2,279 (669) | 2,548 (607) | 30 (646) | 42 (409) | 31 (186) |
| 100 | 2,283 (577) | 2,544 (567) | 30 (612) | 40 (362) | 30 (207) |

Status counts per step: 1 users {'200': 98}; 10 users {'200': 1095}; 50 users {'200': 3159, '429': 515, '503': 2836}; 100 users {'200': 2914, '429': 8602, '503': 3102}.
