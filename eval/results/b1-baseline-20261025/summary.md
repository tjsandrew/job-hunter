# B1 responsiveness baseline (2026-10-25T09:55 – 10:15 UTC)

One warm user, 0.1 s between requests. Client = Locust on the operator laptop (includes network). Server = API Gateway access log (gateway total / time in the API function). Milliseconds.

| Endpoint | Group | Target P95 | Requests | Failures | Client P50 / P95 / P99 | Server P50 / P95 / P99 | Lambda P50 / P95 | Meets target |
|---|---|---|---|---|---|---|---|---|
| `/applications` | browse | 500 | 186 | 0 | 78 / 250 / 250 | 63 / 71 / 100 | 61 / 70 | yes |
| `/documents` | browse | 500 | 186 | 0 | 76 / 250 / 310 | 61 / 71 / 111 | 60 / 69 | yes |
| `/jobs/reviewed` | browse | 500 | 186 | 0 | 78 / 250 / 260 | 63 / 78 / 144 | 62 / 73 | yes |
| `/jobs/{id}` | browse | 500 | 186 | 0 | 85 / 250 / 250 | 64 / 78 / 112 | 63 / 72 | yes |
| `/me` | browse | 500 | 187 | 0 | 76 / 250 / 250 | 61 / 71 / 120 | 59 / 67 | yes |
| `/profile` | browse | 500 | 186 | 0 | 76 / 250 / 270 | 60 / 71 / 123 | 59 / 68 | yes |
| `/profile/bank` | browse | 500 | 186 | 0 | 83 / 250 / 260 | 65 / 73 / 118 | 64 / 72 | yes |
| `/recommendations` | browse | 500 | 186 | 0 | 2100 / 2300 / 2400 | 2069 / 2212 / 2235 | 2066 / 2211 | **no** |
| `/recommendations/for-you` | ranking | 2000 | 186 | 0 | 2500 / 2600 / 2700 | 2377 / 2521 / 2569 | 2376 / 2517 | **no** |

Access-log status counts in the window: {'200': 1676}.
