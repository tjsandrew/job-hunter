# B2 AI task timings (2026-10-25T18:48 – 18:49 UTC)

Model: `hosted:gemma4:26b`. One request at a time; fit analysis polled every second. Seconds.

| Task | Ready / runs | Accept P50 / P95 | Complete P50 / P95 / max | Within 30 s | Failures |
|---|---|---|---|---|---|
| Fit analysis | 0 / 0 | – (answered in the request) | – / – / – | 0 / 0 | none |
| AI cover letter | 0 / 0 | – (answered in the request) | – / – / – | 0 / 0 | none |
| AI resume rewrite | 15 / 15 | – (answered in the request) | 4.4 / 6.7 / 6.7 | 15 / 15 | none |

Where the time goes (means over runs joined to the worker log):

| Task | Waiting for worker | Model calls | Rest of worker | Polling and API | Model calls per run | Prompt / output tokens per run |
|---|---|---|---|---|---|---|
| Fit analysis | – | – | – | – | – | – |
| AI cover letter | – | – | – | – | – | – |
| AI resume rewrite | 1.0 | 2.8 | 0.2 | 0.8 | 1.0 | 872 / 86 |
