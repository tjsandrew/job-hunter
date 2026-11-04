# B1 responsiveness baseline (2026-11-04T16:55 – 17:15 UTC)

One warm user, 0.1 s between requests. Client = Locust on the operator laptop (includes network). Server = API Gateway access log (gateway total / time in the API function). Milliseconds.

| Endpoint | Group | Target P95 | Requests | Failures | Client P50 / P95 / P99 | Server P50 / P95 / P99 | Lambda P50 / P95 | Meets target |
|---|---|---|---|---|---|---|---|---|
| `/applications` | browse | 500 | 218 | 0 | 35 / 41 / 50 | 23 / 28 / 34 | 22 / 27 | yes |
| `/documents` | browse | 500 | 218 | 0 | 35 / 42 / 46 | 24 / 29 / 35 | 22 / 28 | yes |
| `/jobs/reviewed` | browse | 500 | 218 | 0 | 35 / 43 / 48 | 24 / 31 / 36 | 23 / 29 | yes |
| `/jobs/{id}` | browse | 500 | 218 | 0 | 37 / 44 / 98 | 24 / 31 / 85 | 23 / 30 | yes |
| `/me` | browse | 500 | 219 | 0 | 35 / 42 / 50 | 23 / 29 / 38 | 22 / 27 | yes |
| `/profile` | browse | 500 | 218 | 0 | 34 / 41 / 45 | 23 / 28 / 33 | 22 / 27 | yes |
| `/profile/bank` | browse | 500 | 218 | 0 | 41 / 50 / 58 | 27 / 34 / 40 | 26 / 32 | yes |
| `/recommendations` | browse | 500 | 218 | 0 | 2000 / 2100 / 2200 | 1983 / 2071 / 2122 | 1981 / 2070 | **no** |
| `/recommendations/for-you` | ranking | 2000 | 218 | 0 | 2300 / 2400 / 2500 | 2257 / 2363 / 2486 | 2255 / 2361 | **no** |

Access-log status counts in the window: {'200': 1939}.
