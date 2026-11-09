# B2 AI task timings (2026-11-04T17:15 – 17:26 UTC)

Model: `hosted:gemma4:26b`. One request at a time; fit analysis polled every second. Seconds.

| Task | Ready / runs | Accept P50 / P95 | Complete P50 / P95 / max | Within 30 s | Failures |
|---|---|---|---|---|---|
| Fit analysis | 15 / 15 | 110 / 398 ms | 23.9 / 33.5 / 33.5 | 10 / 15 | none |
| AI cover letter | 15 / 15 | – (answered in the request) | 10.3 / 14.3 / 14.3 | 15 / 15 | none |
| AI resume rewrite | 15 / 15 | – (answered in the request) | 4.2 / 7.2 / 7.2 | 15 / 15 | none |

Where the time goes (means over runs joined to the worker log):

| Task | Waiting for worker | Model calls | Rest of worker | Polling and API | Model calls per run | Prompt / output tokens per run |
|---|---|---|---|---|---|---|
| Fit analysis | 1.0 | 23.7 | 0.2 | 0.5 | 4.7 | 3160 / 1136 |
| AI cover letter | 0.9 | 9.1 | 0.2 | 0.5 | 1.0 | 991 / 497 |
| AI resume rewrite | 0.8 | 2.9 | 0.1 | 0.6 | 1.0 | 821 / 84 |
