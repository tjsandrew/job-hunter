# B2 AI task timings (2026-10-25T13:07 – 13:18 UTC)

Model: `hosted:gemma4:26b`. One request at a time; fit analysis polled every second. Seconds.

| Task | Ready / runs | Accept P50 / P95 | Complete P50 / P95 / max | Within 30 s | Failures |
|---|---|---|---|---|---|
| Fit analysis | 15 / 15 | 166 / 489 ms | 26.1 / 34.5 / 34.5 | 12 / 15 | none |
| AI cover letter | 15 / 15 | – (answered in the request) | 11.4 / 13.6 / 13.6 | 15 / 15 | none |
| AI resume rewrite | 10 / 15 | – (answered in the request) | 4.3 / 5.3 / 5.3 | 10 / 10 | The AI model returned an unexpected result |

Where the time goes (means over runs joined to the worker log):

| Task | Waiting for worker | Model calls | Rest of worker | Polling and API | Model calls per run | Prompt / output tokens per run |
|---|---|---|---|---|---|---|
| Fit analysis | 0.9 | 24.3 | 0.2 | 0.8 | 4.6 | 3253 / 1141 |
| AI cover letter | 0.9 | 9.5 | 0.2 | 0.7 | 1.0 | 1054 / 516 |
| AI resume rewrite | 0.9 | 2.8 | 0.1 | 0.6 | 1.0 | 835 / 88 |
