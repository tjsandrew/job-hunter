# B1 rerun after PR #35 (keyword ranking speed-up)

Run: 27 October 2026, 14:46–15:06 UTC, staging at 17b4365, same scenario, client and analysis as the first B1
(`../b1-baseline-20261025/`). The evaluation accounts were reset first (`eval/reset_reviews.py`) so the listings rank
the whole pool (518 jobs, against 508 in the first run) as they did then. 2,590 requests, no failures; three other
requests in the window (one 201, two 404) came from someone else using staging.

| Endpoint (server side, ms) | First B1: P50 / P95 / P99 | After PR #35: P50 / P95 / P99 | P95 change | Target |
|---|---|---|---|---|
| All jobs `/recommendations` | 2,069 / 2,212 / 2,235 | **1,271 / 1,646 / 1,673** | −26% | 500 ms browse: missed (under 2 s) |
| For you `/recommendations/for-you` | 2,377 / 2,521 / 2,569 | **1,593 / 1,991 / 2,136** | −21% | 2 s: met at P95 by 9 ms; P99 over |
| Seven plain endpoints | 60–65 / 71–78 / 100–144 | 69–76 / 79–116 / 97–201 | within noise | 500 ms: met |

- **PR #35 cut the listings by about a quarter at P95 and over a third at the median.** It caches each job's token
  counts per Lambda instance and skips most of the skill-regex work; results are unchanged.
- **For you now meets its target, with no margin.** P95 1,991 ms against 2,000; P99 2,136 ms. A larger pool will
  push it back over, because the remaining work still grows with the number of jobs.
- **All jobs stays over the 500 ms browse target.** If the team classes it as ranking (it does rank, by keywords),
  it meets the 2 s ranking target with room.
- The cache is per Lambda instance: each new instance's first listing request pays the full cost. This run used one
  warm instance, so it shows the best case.

## A confounded attempt, not used

An attempt earlier the same evening measured 783 / 937 ms (All jobs) and 1,062 / 1,201 ms (For you). It was run
on accounts still holding about 330 saved or passed jobs each from the B3 load tests. The listings leave those out,
so that run ranked only about 184 jobs. The same leftovers made `/applications` slower (303 ms P95 with ~170 saved
jobs: the tracker is returned in one unpaginated response). The load test now undoes each Save/Pass straight away,
and `eval/reset_reviews.py` clears any left behind.
