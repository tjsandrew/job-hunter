# B3 step load: per step (server side)

Last 300 s of each step. Latency is API Gateway's, for successful (2xx) requests, in ms. 429 = the gateway's deliberate rate cap; 5xx = errors (includes the API function hitting its reserved concurrency).

| Users | Window (UTC) | Requests/s | 2xx/s | P50 / P95 / P99 | 429 | 5xx | Lambda conc. max | Lambda throttles | Aurora ACU max | DB conn. max | DB CPU avg / max |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 03:05:05–03:10:05 | 0.3 | 0.3 | 131 / 2,001 / 2,039 | 0 | 0 | 1 | 0 | 1.00 | 1 | 65 / 100% |
| 10 | 03:11:05–03:16:05 | 3.4 | 3.4 | 88 / 2,229 / 2,401 | 0 | 0 | 9 | 0 | 1.00 | 4 | 96 / 100% |
| 50 | 03:17:05–03:22:05 | 20.1 | 10.6 | 130 / 2,170 / 2,309 | 0 | 2858 | 10 | 2,246 | 1.00 | 10 | 100 / 100% |
| 100 | 03:23:05–03:28:05 | 44.8 | 10.8 | 145 / 2,036 / 2,218 | 7431 | 2758 | 10 | 2,190 | 1.00 | 10 | 100 / 100% |

P95 by endpoint (2xx only, ms; count in brackets):

| Users | `GET /recommendations` | `GET /recommendations/for-you` | `GET /jobs/{id}` | `PUT /jobs/{id}/review` | `GET /me` |
|---|---|---|---|---|---|
| 1 | 1,725 (19) | 2,023 (29) | 131 (16) | 96 (5) | 78 (5) |
| 10 | 2,003 (243) | 2,401 (214) | 105 (204) | 93 (73) | 90 (65) |
| 50 | 1,967 (680) | 2,300 (726) | 159 (639) | 185 (225) | 148 (231) |
| 100 | 1,853 (687) | 2,205 (681) | 187 (692) | 202 (245) | 179 (227) |

Status counts per step: 1 users {'200': 99}; 10 users {'200': 1030}; 50 users {'200': 3177, '503': 2858}; 100 users {'200': 3249, '429': 7431, '503': 2758}.
