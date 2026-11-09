# Documentation

Start with the [project README](../README.md) for what Job Hunter is and what runs now. This folder holds the detail behind it.

## What runs now

| Document | What it covers |
|---|---|
| [architecture/aws-overview.md](architecture/aws-overview.md) | What runs where on AWS: diagram, request flows, what can reach the internet, and why it is shaped this way ([styled HTML copy](architecture/aws-overview.html)) |
| [deployment/README.md](deployment/README.md) | Deployment guide: AWS resources, credentials, release and pause/resume workflows, cost guards, Terraform state |
| [deployment/JOB-PULL-ROLLOUT.md](deployment/JOB-PULL-ROLLOUT.md) | The twice-daily job pull: Discovery and Import Lambdas, schedule, safety and cost |
| [deployment/EMBEDDING-WORKER-ROLLOUT.md](deployment/EMBEDDING-WORKER-ROLLOUT.md) | Operating the embedding worker (S3 flag, SQS, Lambda) |
| [LOCAL-DEVELOPMENT.md](LOCAL-DEVELOPMENT.md) | Local stack, job imports, AI and embedding settings, demo reset, where the resume editor code lives |
| [status/FEATURES.md](status/FEATURES.md) | Features against the preliminary report's commitments, and what was left out |
| [status/PENDING.md](status/PENDING.md) | Known limitations and future work |
| [../eval/README.md](../eval/README.md) | System evaluation: load, AI task timing, job-pull pipeline, dedup accuracy, acceptance checks and cost, with raw results |

## Design and reasons

The [design briefs](design/README.md) describe each component as built, with the decisions made and why. [CONTRACTS.md](design/CONTRACTS.md) holds the shared API and data contracts.

| Brief | Topic |
|---|---|
| [01](design/01-INFRASTRUCTURE.md) | Infrastructure and deployment |
| [02](design/02-BACKEND-AND-DATA.md) | Backend, database, tenant isolation and tasks |
| [03](design/03-PROFILES-AND-RESUMES.md) | Profiles and resume upload |
| [04](design/04-JOB-INGESTION.md) | Job discovery, deduplication and the job pull |
| [05](design/05-RECOMMENDATIONS.md) | Recommendations and ranking |
| [06](design/06-APPLICATION-PREPARATION.md) | Fit analysis and application documents |
| [07](design/07-FRONTEND.md) | Frontend and user journey |
| [08](design/08-INTEGRATION-AND-EVALUATION.md) | Integration and evaluation |
| [09](design/09-RESUME-EDITOR.md) | Resume editor |
| [10](design/10-PROFILE-BANK.md) | Profile bank |
| [11](design/11-EMBEDDING-WORKER.md) | Embedding worker on AWS |
| [12](design/12-FIT-ANALYSIS.md) | Fit analysis and the shared LLM worker |
| [13](design/13-PRICING-AND-PLANS.md) | Pricing and plans (premium is a demo plan for now) |
| [14](design/14-COVER-LETTERS.md) | Cover letters |
