# B3 run 1 notes: current limits

Run: 26 October 2026, 03:04–03:28 UTC (11:04–11:28 SGT), staging at 5be97cd. API function reserved concurrency 10;
gateway 20 req/s, burst 40; Aurora 0–1 ACU. Laptop client (lid open, `caffeinate`); an earlier attempt on 25 October
was aborted when the laptop slept and is not used.

## Result

| Users | Offered req/s | Successful req/s | Refused by gateway (429) | Failed (503) | P95 of successful |
|---|---|---|---|---|---|
| 1 | 0.3 | 0.3 | 0 | 0 | 2.0 s |
| 10 | 3.4 | 3.4 | 0 | 0 | 2.2 s |
| 50 | 20.1 | 10.6 | 0 | 2,858 (47%) | 2.2 s |
| 100 | 44.8 | 10.8 | 7,431 (55%) | 2,758 (21%) | 2.0 s |

(Per 300-second steady window; P95 over all endpoints is dominated by the two recommendation listings.)

- **Saturation point: about 10.7 successful requests per second**, reached between 10 and 50 users. With this
  browsing mix (about 0.34 requests per user per second) that is roughly 30 concurrent users.
- **The binding limit is the API function's reserved concurrency of 10.** Concurrency sits at exactly 10 from the
  50-user step on, Lambda reports about 2,200 throttles per minute-window, and API Gateway turns each throttled
  invocation into a `503`. The theoretical ceiling is 10 / 0.85 s mean duration ≈ 11.8 req/s.
- **The gateway's rate limit (20 req/s, burst 40) bites at 100 users**, refusing 55% of requests with `429`
  before they reach the function. Of the ~20 req/s it lets through, about half are then throttled by the function.
- **The caps shed load instead of queueing it.** Requests that get through are as fast as at low load: P95 of the
  plain endpoints goes from about 90 ms to about 200 ms, the listings stay at 1.9–2.3 s, mean function duration
  does not rise (943 → 770 ms), and there are no function errors. Users past the cap get a fast refusal, not a slow
  page.

## The database is the next bottleneck

Aurora's CPU at 1 ACU averages **65% with a single user** (72% in the B1 baseline), **96% at 10 users** and 100% from
50 users on. Capacity stays at its 1 ACU maximum throughout; connections peak at 10, one per function instance.
Function durations did not rise, so the database is not yet slowing requests, but it has no headroom: raising the
function's concurrency alone would most likely move the bottleneck to the database. The likely load is the
recommendation listings, which read every open job (and, for For you, compare embeddings) on each request.

## For run 2

Raise all three together, as the A5 runbook says: API concurrency 50, gateway 200/s burst 400, `aurora_max_acu` 4.
Expect the successful throughput to rise until either Aurora CPU at 4 ACU or the listings' per-request cost becomes
the limit; watch Aurora CPU and function duration for the first signs.

## Method notes

- Step windows are the last 300 s at each user count, from Locust's per-second history. CloudWatch values use only
  the whole minutes inside each window.
- `503` here is API Gateway's response to a throttled Lambda invocation (confirmed by the Lambda `Throttles`
  metric); `429` is the gateway's own rate limit. Neither reaches the API code.
- Client-side numbers (Locust) include the home Wi-Fi and count fast refusals, so they are not used for latency.
