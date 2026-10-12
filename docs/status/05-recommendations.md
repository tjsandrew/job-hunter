# Handoff 05 — Local job recommendations

## Implemented interface

`backend/src/job_hunter/recommendations.py` exports `rank_jobs(jobs, profile, preferences) -> list[dict]`. It accepts plain mappings so the caller can adapt ORM, API, or fixture records without coupling the ranking function to SQLAlchemy. Each returned item contains the original `job` mapping, stable `rank`, numeric `score` with label `relevance score (not probability)`, component values, exact skill/role/location evidence, a readable reason, `ranking_version`, and mode (`local_hybrid` or `cold_start`). The module has no network, model, vector, or persistence calls.

The intended route integration passes open shared jobs already filtered to the current user, their active confirmed profile data, and preference JSON. The route should keep tenant ownership, prior review exclusions, pagination, and authorization outside this pure ranker. No `main.py` route was changed in this handoff.

## Ranking behavior

The text component is cosine similarity over local TF-IDF vectors built from the selected profile fields (`summary`, `headline`, `professional_summary`, `about`, skills, experience titles/skills, and role preferences) against job title, description, declared skills, category, and department. No names, contact fields, or protected-trait fields are included. Email/phone patterns and protected-trait terms are removed from text tokens. Skill matching is exact after a small documented alias map; SQL and NoSQL are separate. Reasons cite the literal skill phrase and whether it appeared in the explicit `job.skills`, title, or description. Role alignment compares target/experience role terms against the job title.

The available components are combined with weights 0.50 text, 0.35 skill overlap, and 0.15 role alignment; when a component has no input, the remaining weights are renormalized. The score is deterministic, bounded from 0 to 1, and is only a within-list relevance value. It is not a probability or hiring-success estimate. Ties break by newest posting/retrieval timestamp, then stable job identity, then original input order.

Open status is required. Selected locations and work modes are hard eligibility filters. A missing job location passes only when no location filter is selected; a selected location plus unknown job location is excluded. Likewise, a selected work mode excludes jobs with unknown mode. Singapore aliases `SG` and `SGP` match explicit Singapore text. No employer headquarters or description text is used to infer job location. Salary filtering is outside this local v1; missing salary is retained as unknown.

When there are no usable profile or role signals, eligible jobs return with score zero, stable freshness ordering, `cold_start` mode, and a prompt to add profile details. Empty eligibility returns an empty list. No synthetic embeddings or semantic model claims are made.

## Synthetic evaluation

`backend/tests/test_recommendations.py` uses two contrasting synthetic profiles and two jobs. The SQL analyst profile ranks the SQL analyst above the machine-learning engineer; the machine-learning profile ranks the ML engineer first. It also covers SQL/NoSQL exactness, Singapore location filtering, unknown locations, work-mode filtering, closed jobs, stable ordering, deterministic evidence, and ignored contact/name/protected fields.

Run:

```sh
PYTHONPATH=backend/src python -m pytest backend/tests/test_recommendations.py -q
```

Result: 9 passed. These are correctness checks on labelled synthetic examples, not a user-quality study. The 70 imported Singapore listings can support a later manual relevance set, but were not used as labelled ground truth. TF-IDF has no learned synonym/semantic understanding; it can miss paraphrases, and the current taxonomy/category signals are rule-based. No PostgreSQL-backed route, review exclusion, cursor, or pagination behavior was verified here.

## API integration and live-pool spot check

The parent integrated the ranker into `/v1/recommendations`. It ranks eligible unreviewed postings using the user's saved profile and preferences, then applies text search and offset pagination. Responses retain `reasons` for the frontend and add ranking version, score label, evidence and component scores. The UI must not convert these scores to match percentages. The frontend's sample profile actions populate an editable draft; users still choose Save.

A read-only local spot check over the 70 imported postings used fictional SQL analyst and ML engineer profiles. SQL's top result was Stripe's Data Analyst, Global Growth; ML's top result was also that data role, followed by broader adjacent roles. The narrow pool has few dedicated ML openings, and company-description boilerplate can contribute lexical matches. This is evidence the path runs, not evidence of measured recommendation quality. One process observed roughly 57–70 ms for rank computation over this pool; that excludes HTTP/database time and is not a latency benchmark or percentile claim. Evaluate with user-labelled relevance and broader job coverage before asserting recommendation quality.
