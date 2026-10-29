# B2 re-run: AI resume rewrite after the shape fix

Run: 25 October 2026, 18:48 UTC, staging at 5be97cd (PR #33). Same 15 jobs and accounts as
`b2-ai-tasks-20261025T130734Z`, rewrite only. No AI uses spent (each job already held this month's slot).

| | Before (PR #32 build) | After (PR #33) |
|---|---|---|
| Rewrites accepted | 10 of 15 | **15 of 15** |
| Completion P50 / P95 | 4.3 / 5.3 s | 4.4 / 6.7 s |
| Model calls per run | 1.0 | 1.0 (no retries needed) |
| Prompt / output tokens per run | 835 / 88 | 872 / 86 |

- **All 15 passed on the first model call**, so the improvement comes from leaving out the entries that have no
  bullets, not from the retry. The retry remains as a safety net and was never triggered here.
- If both runs had the same underlying failure rate, the chance of all five failures falling in the first run is
  about 2% (one-sided Fisher exact test, 10/15 vs 15/15). The sample is small; the result is consistent with the
  cause identified from the failed replies (the model dropping, adding or merging entries around the empty one).
- No cost in time or tokens: the medians are within 0.1 s. The 6.7 s maximum is the first request of the run.
- One run ("Senior Backend Developer") returned `unchanged`: the reply was accepted but every reworded bullet was
  either the same or reverted by the fact check. It counts as a successful call; no AI use is charged for it.
