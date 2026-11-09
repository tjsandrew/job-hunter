# B2 rerun on main 63b8ff5 (5 November 2026, 01:15–01:27 SGT)

Same runner, accounts and model (`gemma4:26b` on SoClaaS) as `../b2-ai-tasks-20261025T130734Z/`. November's
allowance had reset, so this used 15 of the 30 new AI uses on `jh-eval-01..05` (3 jobs each, all three tasks per
job). Jobs are each account's current For you picks, so they differ from October's.

| Task | Target | 25 Oct | **5 Nov** |
|---|---|---|---|
| Fit analysis accepted (server) | < 200 ms | 121–177 ms for 14 of 15, 252 ms first | **60–140 ms for 14 of 15, 368 ms first** |
| Fit analysis ready | < 30 s | 26.1 s median, 34.5 s P95, 12/15 within 30 s | **23.9 s median, 33.5 s P95, 10/15 within 30 s** |
| AI cover letter | (synchronous) | 11.4 s median, 15/15 | **10.3 s median, 14.3 s max, 15/15** |
| AI resume rewrite | (synchronous) | 4.3 s, 10/15 (15/15 after PR #33) | **4.2 s median, 7.2 s max, 15/15** |

- **Acceptance is faster** (connection reuse and 2 GB). The first request of the run still pays a cold start.
- **Fit analysis is unchanged in substance:** 4.7 model calls in sequence take 23.7 s of the 23.9 s median, and
  5 of 15 runs went over 30 s (30.4–33.5 s). What predicts a slow run is how many requirements the model extracts, which sets how much checking follows: 4 of the 5 slow runs had 15 requirements, the 10 within 30 s had 8–15 (median 10). Posting length matters less. The fix is in how the model is called (fewer
  or parallel calls), not in the infrastructure, which adds about 1.7 s.
- **The rewrite shape fix holds:** 15 of 15 on new jobs, first call each time.
- Tokens per task are as in October: fit 3,160 in / 1,136 out, cover letter 991 / 497, rewrite 821 / 84.
