# B1 responsiveness baseline (2026-10-27T14:46 – 15:06 UTC)

One warm user, 0.1 s between requests. Client = Locust on the operator laptop (includes network). Server = API Gateway access log (gateway total / time in the API function). Milliseconds.

| Endpoint | Group | Target P95 | Requests | Failures | Client P50 / P95 / P99 | Server P50 / P95 / P99 | Lambda P50 / P95 | Meets target |
|---|---|---|---|---|---|---|---|---|
| `/applications` | browse | 500 | 259 | 0 | 82 / 100 / 160 | 71 / 80 / 165 | 69 / 78 | yes |
| `/documents` | browse | 500 | 259 | 0 | 82 / 95 / 150 | 71 / 84 / 171 | 69 / 83 | yes |
| `/jobs/reviewed` | browse | 500 | 259 | 0 | 83 / 110 / 160 | 72 / 81 / 97 | 71 / 80 | yes |
| `/jobs/{id}` | browse | 500 | 259 | 0 | 83 / 110 / 160 | 72 / 79 / 105 | 70 / 77 | yes |
| `/me` | browse | 500 | 260 | 0 | 82 / 130 / 160 | 71 / 92 / 182 | 69 / 91 | yes |
| `/profile` | browse | 500 | 259 | 0 | 81 / 110 / 160 | 70 / 116 / 201 | 69 / 115 | yes |
| `/profile/bank` | browse | 500 | 259 | 0 | 88 / 100 / 150 | 76 / 100 / 152 | 74 / 98 | yes |
| `/recommendations` | browse | 500 | 259 | 0 | 1300 / 1700 / 1700 | 1271 / 1646 / 1673 | 1267 / 1645 | **no** |
| `/recommendations/for-you` | ranking | 2000 | 259 | 0 | 1600 / 2000 / 2000 | 1593 / 1991 / 2136 | 1592 / 1989 | yes |

Access-log status counts in the window: {'200': 2500, '201': 1, '404': 2}.
