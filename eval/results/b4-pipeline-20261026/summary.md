# B4 job pipeline: every pull on staging

| Pull (UTC) | Fetched | greenhouse | lever | mycareersfuture | adzuna | Cross-source duplicates | New / already stored / deferred | Discovery s | Import s | To embedded s | Failures | Truncated searches |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-24T15:48 | 1096 | 57 | 11 | 978 | 50 | 0 | – / – / – | 29.4 | 6.8 | – | 1 | 2 |
| 2026-10-24T16:28 | 1098 | 58 | 11 | 979 | 50 | 0 | – / – / – | 108.2 | 8.3 | – | 0 | 2 |
| 2026-10-25T08:09 | 1084 | 58 | 11 | 967 | 48 | 2 | – / – / – | 38.3 | 9.2 | – | 0 | 2 |
| 2026-10-25T09:20 | 2177 | 58 | 11 | 2058 | 50 | 2 | – / – / – | 93.9 | 20.3 | – | 0 | 2 |
| 2026-10-26T04:20 | 2169 | 58 | 11 | 2050 | 50 | 2 | 10 / 442 / 1717 | 166.8 | 12.8 | 193.2 | 0 | 2 |

Pulls: 5. Failures by kind: {'greenhouse:cloudflare response_too_large': 1}.
Truncated searches (more postings than one pull reads): adzuna:data engineer, mycareersfuture:software engineer.
New / already stored / deferred are known only for pulls run with eval/b4_pull.py (the workflow writes them to its job summary, which is not kept).
