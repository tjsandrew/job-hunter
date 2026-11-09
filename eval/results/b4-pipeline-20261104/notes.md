# B4 rerun: job pipeline with the EventBridge schedule (tallied 5 November 2026)

45 pulls on record: 37 started by hand (24–31 October; most on 31 October, when the team loaded the larger pool by
running pulls back to back) and **8 started by the EventBridge schedule** (1–4 November, twice a day). The scheduled
pulls are the "per scheduled run" figures the preliminary report asks for. New / already stored / deferred come
from the discovery function's per-pull log line (PR #39).

## Scheduled pulls (1–4 November)

| Pull (SGT) | Fetched | New | Deferred | Source failures | Discovery | Import | Import start → embedded (rankable in For you) |
|---|---|---|---|---|---|---|---|
| 1 Nov 08:06 | 4,807 | 111 | 0 | 3 | 422 s | 47 s | 152 s |
| 1 Nov 20:06 | 5,698 | 102 | 0 | 0 | 393 s | 39 s | 89 s |
| 2 Nov 08:04 | 1,596 | 22 | 0 | 14 | 255 s | 34 s | 65 s |
| 2 Nov 20:06 | 5,734 | 150 | 232 | 0 | 413 s | 53 s | 154 s |
| 3 Nov 06:06 | 5,705 | 150 | 130 | 0 | 423 s | 48 s | 179 s |
| 3 Nov 20:06 | 5,789 | 150 | 269 | 0 | 439 s | 52 s | 219 s |
| 4 Nov 06:07 | 5,757 | 150 | 163 | 0 | 487 s | 42 s | 158 s |
| 4 Nov 20:08 | 4,835 | 150 | 198 | 3 | 500 s | 37 s | 143 s |

- **Volume:** about 5,700 Singapore postings per complete pull across 21 MyCareersFuture searches, Greenhouse (≈55),
  Adzuna (50) and Lever (7). MyCareersFuture is 97% of it.
- **New jobs per run: 102–150**, capped at 150 since 2 November; 130–269 new postings a run are left for the next
  pull, so the cap still binds.
- **Reliability: 5 of 8 scheduled pulls were complete; 2 lost 3 searches each to MyCareersFuture timeouts and one
  (2 Nov 08:04) lost most of them (14 failures, 1,596 fetched).** That pull led to PR #52 (deployed 2 Nov 16:35 UTC):
  slow sources are retried once with 30 s waits, and the limit is 900 s. Since then, 3 of 4 pulls were complete
  and one lost 3 searches. Adzuna returned two server errors over the whole period; no malformed records; no
  rate limiting.
- **Processing latency** (the preliminary report's definition, from the worker picking up the work to the records
  being queryable): **import 34–53 s** (jobs in All jobs), **65–219 s, median 153 s, until embedded** (rankable in
  For you), for 22–150 new jobs.
- **Discovery is slowing down:** 255–500 s a pull, rising since 2 November as searches return more pages, against a 900 s
  limit (raised from 300 s and then 600 s in PRs #44 and #52).
- Nine searches are truncated on every complete pull (more than 5 pages of 100), so some postings are never read.
- Cross-source duplicates found by the production rules: 1–3 per pull out of about 5,700.

Duplicate-removal accuracy is unchanged (`../b4-dedup-20261104/`): the matching rules have not changed since 26 October.
