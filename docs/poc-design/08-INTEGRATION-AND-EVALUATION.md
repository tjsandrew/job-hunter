# 08 — Integration, evaluation and POC acceptance

**Current delivery scope:** [local application first; AWS-native services later](DELIVERY-SCOPE.md). This staging rule overrides earlier cloud requirements for the local milestone.

**Portability requirement:** follow [LOCAL-TO-AWS.md](LOCAL-TO-AWS.md). Keep this component’s logic shared between local Docker execution and AWS; record adapter differences and unverified cloud checks in its handoff.

Read [README](README.md) and [contracts](CONTRACTS.md). Own cross-component tests, evaluation scripts/fixtures and final evidence. Follow Section 4 of the group's report; distinguish measured outcomes from provisional targets.

## Unit-test coordination and quality gate

Each feature/component must arrive with its relevant unit tests; do not defer unit testing until final integration. Require deterministic, network-free unit suites and separate commands/markers for PostgreSQL/component, cloud integration and browser end-to-end tests. Unit tests run on every change/PR alongside type checks and linting. Run affected tests during development and the complete unit suite before handing off a component.

Track coverage to identify missing critical branches, especially ownership decisions, quotas, retries, version conflicts and malformed input. Do not use an arbitrary coverage percentage as proof of quality. Tests must assert observable behaviour or independently derived expectations, not merely mirror implementation code. Add a regression test for each meaningful defect fixed.

CI must not need AWS credentials, live source credentials or paid inference to run unit tests. Run database integration tests using a disposable PostgreSQL/pgvector service. Cloud smoke tests require an explicitly configured test environment; browser tests may run against local seeded services. Record skipped integration tests and reasons honestly.

## Applying these gates by milestone

Run local unit/database/browser gates now. Defer Cloud slice, AWS delivery/outbox/distributed lease tests, cloud load measurements and cloud costs until the AWS milestone. Keep live source discovery active locally. Model-quality evaluation requires a real model; mocked flows pass only workflow tests.

## Integration gates

| Gate | Evidence required |
|---|---|
| Foundation | Empty DB migrates; synthetic data seeds; two-user isolation and task/quota tests pass |
| Complete local slice | Upload/manual profile → confirm → fixture recommendations → save → track works without manual DB edits |
| Cloud slice | Cognito/API/RDS/S3/SQS real integration smoke test; mock model/source status explicitly labelled |
| Live discovery | One permitted live source fetches current jobs end to end; two independent live sources meet the multi-source target. Fixture-only discovery remains incomplete. |
| Full preparation | Real or labelled fake model → analysis → editable CV/cover letter → reviewed PDF exports |
| Recovery | Duplicate messages, queue send failure, provider timeout, expired lease, malformed output and late completion preserve state/allowance |
| Acceptance | Representative users finish the agreed journey; critical issues resolved and affected scenarios retested |

Avoid treating a successful UI demo as proof of tenant isolation or reliable delivery. Run database/queue fault tests as well.

## System experiments

Retain the report's proposed levels: 1, 10, 50 and 100 concurrent users. Use Locust or equivalent with a documented mix of browse/profile/tracking requests, separate asynchronous task requests, dataset size and test duration. Reuse the same scenario for comparisons. Low POC concurrency caps may intentionally throttle; measure that result rather than raising limits blindly.

Report P50/P95/P99 latency, throughput, 4xx throttles, 5xx errors and saturation. Record cold and warm API results separately and also the combined user-observed distribution. Provisional report targets: read/browse <500 ms, ranking <2 s, task acceptance <200 ms, asynchronous completion <30 s. These are targets to assess, not guaranteed SLOs. Define whether each is a percentile target before running experiments.

Measure async end-to-end time from accepted request through queue wait, inference, persistence and export; report stage times. Immediate outbox send should support the healthy path. A repaired send can wait up to the one-minute maintenance interval and exceeds the 30-second target; count/report recovery separately without excluding it from reliability results.

Discovery evaluation: new unique jobs by source/run; malformed/rate-limited/failed requests; discovery backlog; processing latency; true/false duplicate merges. Report both duplicate precision and recall on labelled pairs. Do not claim live coverage from fixture results.

Matching evaluation: keyword-only, semantic-only and hybrid on identical labelled queries/jobs. Record precision@K or nDCG@K, sample size, assessor process and disagreements. Evaluate fit/draft grounding separately from relevance. Do not equate ranking scores with hiring outcomes.

## User evaluation

Use consented or synthetic resumes; record participant count and recruitment characteristics rather than inventing them. Ask participants to upload/correct a profile, set preferences, find suitable jobs, save/dismiss, inspect fit evidence, edit/download a draft and update tracking. Include CV editing as well as cover letters because both are promised.

Record task completion/time, assistance, errors, five-point usefulness/control/relevance ratings and open feedback. For a manual comparison, use equivalent tasks/data, counterbalance order where feasible and document limitations. Separate usability success from recommendation quality; small samples are exploratory.

## Cost comparison required by the course

Produce a worksheet for idle development, light usage and the measured load scenario. Use dated Singapore-region prices and actual resource settings. Include RDS/storage/backups, NAT hours/data, Lambda requests/duration, API Gateway, SQS, S3/CloudFront/transfer, Cognito where applicable, Secrets Manager, logging and Bedrock token/embedding usage. Include any subsequently introduced endpoints or proxy. Show credits/free-tier discounts separately from undiscounted costs.

Compare with a fixed-capacity local/on-premise deployment of the same feature set and comparable measured capacity: hardware amortisation, storage/backups, electricity/network and operational assumptions. Keep external model/API expenses on both sides if both use them. Do not count cloud credits as an inherent architectural advantage or assume a desktop offers production availability.

Also compare the proposed Lambda design with the preliminary Fargate + ALB design using explicit workload assumptions. The result may favour different choices at different sustained loads. Record fixed costs separately from per-request/per-user costs.

## Final handoff and demonstration

- One README with prerequisites, environment template, exact local commands, migrations/seeding, tests and authorised cloud deployment/cleanup steps.
- Architecture diagram and actual differences from this proposed design.
- Per-component completion notes with tests, limitations and mock/live status.
- Repeatable demo fixture mode if a provider is unavailable, clearly labelled.
- Evaluation results, known issues, source/model provenance and dated cost worksheet.
- Course-ready code explanation and accurate AI-assistance disclosure, including how generated work was checked and what the team learned. Public repository publication is a separate user-authorised action; do not publish private data or secrets.

POC acceptance requires the full core journey and honest evidence. If a dependency is unavailable, finish and test its adapter boundary and state exactly which live requirement remains incomplete.
