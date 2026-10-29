# B1 notes

**Result.** All seven plain browse endpoints meet the 500 ms P95 target with a wide margin: about 60–65 ms median
and 70–78 ms P95 server-side, almost all of it in the API function. The two ranking-backed listings do not:

| Endpoint | Target P95 | Server P95 | Verdict |
|---|---|---|---|
| All jobs (`/recommendations`) | 500 ms (browse) | 2,212 ms | misses by about 4.4× |
| For you (`/recommendations/for-you`) | 2,000 ms (ranking) | 2,521 ms | misses by about 26% |

No failures in 1,675 requests; all 1,676 access-log lines in the window are 200 (the one extra line is a request
in flight at the window boundary). No other staging traffic was present.

**Why the listings are slow.** `rank_jobs` (backend/src/job_hunter/recommendations.py) runs on every request over
every open job: it tokenises each job's full title, description and skills, builds TF-IDF vectors for the whole pool
and scores them all, with no caching between requests. The cost therefore grows linearly with the pool: the A2
smoke test measured All jobs at about 1.3 s median with about 309 jobs; with 508 jobs it is 2.1 s. For you adds the
embedding similarity step on top (about 0.3 s more). Options for the report's discussion section: cache the per-job
token counts or vectors when jobs are imported (they only change on a pull), serve All jobs without personalised
scoring, or move the text ranking into the database (full-text search or pgvector, which Aurora PostgreSQL supports).

**Client vs server.** Client-side percentiles are inflated by the operator laptop's Wi-Fi, not by AWS: client P95 is
about 250 ms for endpoints whose server P95 is about 71 ms, the extra time is spread evenly from 0 to about 180 ms,
and pinging the local router alone gave 2.6–124 ms (standard deviation 39 ms). Report the server-side columns as the
system's latency and the client columns as what one user on home Wi-Fi experienced.

**Method.** One warm user cycling nine endpoints with 0.1 s between requests, 1-minute warm-up discarded, 20-minute
measured window (09:55:55–10:15:55 UTC). Server times are API Gateway's responseLatency and integrationLatency from
the access log; percentiles are nearest-rank. Locust rounds its own percentiles (to 10 ms above 100 ms, to 100 ms
above 1 s), so the client columns are coarse.
