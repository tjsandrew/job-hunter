# B1 rerun on main 63b8ff5 (5 November 2026)

20-minute window 16:55–17:15 UTC (00:55–01:15 SGT), one warm user, accounts reset, 1,962 requests, no failures,
no other staging traffic. Server side (API Gateway access log), milliseconds.

| Endpoint | 25 Oct (508 jobs, 1 GB) P50 / P95 | 27 Oct (518 jobs, PR #35) P50 / P95 | **5 Nov (5,905 jobs, 2 GB)** P50 / P95 / P99 | Target |
|---|---|---|---|---|
| Seven plain endpoints | 60–65 / 71–78 | 69–76 / 79–116 | **23–27 / 28–34 / 33–85** | 500 ms: met |
| All jobs `/recommendations` | 2,069 / 2,212 | 1,271 / 1,646 | **1,983 / 2,071 / 2,122** | 500 ms browse: missed (and just over 2 s) |
| For you `/recommendations/for-you` | 2,377 / 2,521 | 1,593 / 1,991 | **2,257 / 2,363 / 2,486** | 2 s: missed by 18% |

- **Plain pages are about 2.5 times faster** (P95 71–78 → 28–34 ms): the API reuses one database connection per
  Lambda instance (PR #50) and has twice the memory, so a full vCPU (PR #51).
- **The listings now rank 11 times as many jobs in about the same time.** Per job, ranking is roughly ten times
  cheaper than on 25 October (in-memory job pool and word-count cache, PR #46; numpy vector comparison, PR #48;
  pool re-checked every 30 s, PR #49; exact skill pre-check, PR #40). But the pool grew faster than the code got
  quicker: at 5,905 jobs both listings are back above 2 s.
- The listings still scale linearly with the pool. At the current 150 new jobs per pull, twice a day, every
  further 1,000 open jobs adds roughly 0.35 s (2,071 ms / 5,905 jobs), unless expired listings are closed at the same rate.
