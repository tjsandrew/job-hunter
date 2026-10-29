# B2 notes

Run: 25 October 2026, 13:07–13:18 UTC, staging at e84e2da (worker metrics logging, PR #32). Model `gemma4:26b` on
SoClaaS. Accounts jh-eval-01..05, three For you jobs each, one request at a time. 15 AI uses spent (one per account
and job; all three tasks on a job share the slot). One extra cover letter from jh-eval-06 checked the log line first
and is not counted.

## Against the targets

| Task | Target | Result | Verdict |
|---|---|---|---|
| Fit analysis: accepted (`202`) | under 200 ms | server 121–177 ms for 14 of 15; 252 ms for the run's first request. Client P50 166 ms | meets, except the first request |
| Fit analysis: ready | under 30 s | P50 26.1 s, P95 34.5 s; 12 of 15 within 30 s | **misses** for 3 of 15 (33–34.5 s) |
| AI cover letter | under 30 s | P50 11.4 s, P95 13.6 s; 15 of 15 | meets |
| AI resume rewrite | under 30 s | P50 4.3 s, P95 5.3 s for the 10 that succeeded | meets on time; **5 of 15 failed** |

Client-side acceptance (P95 489 ms) is inflated by the operator laptop's Wi-Fi, as in B1; the server column is the
system's figure (API Gateway access log, `latencyMs`).

## Where the time goes

Means, from the worker's `llm_task` log lines (all 45 runs joined):

| Task | Waiting for worker | Model | Rest of worker | Polling and API | Model calls | Prompt / output tokens |
|---|---|---|---|---|---|---|
| Fit analysis | 0.9 s | 24.3 s | 0.2 s | 0.8 s | 4.6 | 3,253 / 1,141 |
| AI cover letter | 0.9 s | 9.5 s | 0.2 s | 0.7 s | 1.0 | 1,054 / 516 |
| AI resume rewrite | 0.9 s | 2.8 s | 0.1 s | 0.6 s | 1.0 | 835 / 88 |

- **The model is almost all of it.** S3 notification plus Lambda start averages 0.9 s; the rest of the system adds
  about 1 s. Faster results need fewer or shorter model calls, not infrastructure changes.
- **Fit analysis is slow because it is sequential:** about 4.6 model calls per run, one after another (24 s). The
  three runs over 30 s are the longer postings. Running the per-requirement calls concurrently, or reusing the
  cached requirements for a job already analysed, are the levers.
- **Polling granularity:** the API checks for the worker's answer every second after a one-second pause, so a
  2.8 s model call returns in about 4.2 s (the rewrite times cluster at 4.2 s and 5.2 s).
- The worker is warm for this run (a cold start after the deploy waited 2.7 s on the check request).

## Rewrite failures (5 of 15)

The worker reported `ok` each time, but the API's check (`ai_tailoring.rewrite_content`) rejected the answer because
the model returned a different number of entries than it was sent: it dropped an entry (6 in, 5 out), added one
(7 in, 8 out), or merged all the bullets into two lists (6 in, 2 out). Every successful run kept the shape exactly.
Most inputs include an entry with no bullets (education), which the model tends to drop or merge.

What the user sees: the tailored document is still created with the rule-based changes and `ai.status` is
`fallback`; no AI use is charged (the slot is spent only when the AI changed something).

The rewriter (`preparation/tailor_llm.py`) does not check the shape on the worker side, so there is no retry. The
LLM client already has `complete_validated` (ask, validate, retry once with a repair note), used elsewhere; using it
with a shape check, and leaving out entries that have no bullets (adding them back afterwards), would likely remove
most of these failures. Benchmark history in the code notes the same model nesting the list too deep before the
shape rules were added.

**Fixed and re-measured:** PR #33 (leave out empty entries, validate the shape and retry once) was deployed and the
same 15 rewrites re-run: 15 of 15 accepted, all on the first call. See `../b2-ai-tasks-20261025T184828Z/notes.md`.

## Cost inputs for B5

Per task, mean tokens: fit 3,253 in / 1,141 out over 4.6 calls; cover letter 1,054 / 516; rewrite 835 / 88. Worker
Lambda time per task roughly equals model time plus 0.2 s at 512 MB.
