# B3 run 1 rerun: normal limits, main 63b8ff5 (5 November 2026, 01:27–01:51 SGT)

Same shape and limits as `../b3-run1-20261026/` (API concurrency 10, gateway 20/40 req/s, Aurora 1 ACU), but the API
has 2 GB, the job pool is 5,905 (518 then), and Save/Pass is undone straight away so the pool stays constant (the
October runs let it shrink as the run went on). About 158 undo requests were themselves refused at saturation, so
roughly 25 jobs per account (0.4% of the pool) were left hidden by the end; cleared afterwards.

| Users | Served req/s, 26 Oct → 5 Nov | Refused or failed, 5 Nov | P50 / P95 of served, 5 Nov | Aurora CPU avg, 26 Oct → 5 Nov |
|---|---|---|---|---|
| 1 | 0.3 → 0.3 | 0 | 1,810 / 2,240 ms | 65% → 55% |
| 10 | 3.4 → 3.6 | 0 | 32 / 2,377 ms | 96% → 60% |
| 50 | 10.6 → 10.5 | 52% (2,836 throttled 503, 515 rate-limited 429) | 31 / 2,389 ms | 100% → 64% |
| 100 | 10.8 → 9.7 | 80% (3,102 throttled 503, 8,602 rate-limited 429) | 31 / 2,386 ms | 100% → 65% |

- **The ceiling is unchanged at about 10.5 served requests a second**, set by the API function's concurrency of 10:
  concurrency sits at 10 from 50 users on and Lambda throttles about 2,300–2,400 invocations per step.
- **The database is no longer the bottleneck.** Its CPU averages 55–65% at every load, against 96–100% in October,
  because the job pool and vectors are held in memory and re-read every 30 s instead of on every request.
- **What holds the concurrency is the two listings** (about 2.3 s each). Plain endpoints are served in about 30 ms
  at P95 at every load; the overall P95 is the listings'.
- The P50 at 1 user is high only because one user's cycle is dominated by listing requests.
