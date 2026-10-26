# B3 run 2 notes: raised-capacity window

Run: 26 October 2026, 03:40–04:04 UTC (11:40–12:04 SGT), staging at 5be97cd, same client and scenario as run 1.
Window (A5 runbook): opened 03:38 UTC with API concurrency 50, gateway 200/s burst 400, Aurora maximum 4 ACU;
restored at 04:07 UTC. `config-before.txt` and `config-after.txt` record both states; after restoring, a plain
`terraform plan -var-file=staging.tfvars` showed **No changes**.

## Run 1 vs run 2

| Users | Successful req/s (run 1 → 2) | Failed or refused (run 1 → 2) | P50 / P95 of successful (run 2) | API concurrency max (run 2) | Aurora CPU avg (run 1 → 2) |
|---|---|---|---|---|---|
| 1 | 0.3 → 0.3 | 0 → 0 | 94 / 1,987 ms | 1 | 65% → 15% |
| 10 | 3.4 → 3.6 | 0 → 0 | 85 / 1,911 ms | 9 | 96% → 29% |
| 50 | 10.6 → **18.2** | 47% → **0** | 147 / 1,784 ms | 28 | 100% → 86% |
| 100 | 10.8 → **27.5** | 76% → **0.8%** | **1,158 / 2,794 ms** | **50 (cap)** | 100% → **100%** |

(Run 1 Aurora CPU is at 1 ACU, run 2 at up to 4 ACU. Run 2 offers fewer requests at 100 users than run 1, 28.3 vs
44.8 req/s, because its users wait for real responses instead of getting instant refusals.)

## What it shows

- **Scaling out works up to the database.** With the caps raised, 50 users are served completely (18.2 req/s, no
  errors, latency as at low load) where run 1 refused half their requests. Peak successful throughput rises from
  about 10.7 to 27.5 req/s, about 2.6 times.
- **At 100 users the database is the bottleneck.** Aurora CPU averages 100% at its 4 ACU maximum, mean function
  duration more than doubles (681 → 1,502 ms) because each request waits on the database, and the slower requests
  pile up until the function reaches its new cap of 50 (231 throttled, 0.8%). Plain endpoints that took about
  180 ms at P95 now take about 1.2 s; the median request goes from 147 ms to 1.16 s.
- **Saturation point in run 2: about 27–28 successful req/s, between 50 and 100 users** (roughly 80 users with this
  browsing mix), where latency climbs sharply while throughput stops growing in step with load.
- **The cost per request is what limits scale, not the infrastructure ceiling.** One user already used 65% of
  1 ACU in run 1; quadrupling the database bought about 2.6 times the throughput. The recommendation listings read
  every open job on each request (and For you also compares embeddings), so reducing that work, for example by
  caching the per-job text features at import or indexing the vector search, would raise capacity more cheaply than
  more ACUs.
- Aurora reported 4 ACU already in the 1-user step: it scaled up while waking from its pause during the warm-up and
  came down to 2 ACU in the 10-user step. CPU per ACU, not the ACU figure, is the useful signal here.

## Method notes

As run 1. The 503s at 100 users are Lambda throttles at the raised cap (Lambda `Throttles` 194 in the whole
minutes of the window; the access log counts 231 over the full 300 s). There were no function errors.
