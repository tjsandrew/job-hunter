# Contributing

## Workflow

1. Pull the latest `main` and create a branch: `git checkout -b <your-name>/<short-topic>`.
2. Agree changes to shared contracts ([docs/design/CONTRACTS.md](docs/design/CONTRACTS.md)) before making them.
3. Add or update tests with the code, and run the checks in the [README](README.md#tests).
4. Open a pull request into `main`. CI must pass, and one teammate should review it before merging.

## Rules

- **No secrets or private data in Git.** Do not commit `.env` files, AWS keys, real resumes, or course and report files. Use `.env.example` for configuration names only. Use synthetic fixtures for tests.
- Add AWS resources to Terraform; note any manual resource, its cost and how to remove it in the pull request.
- Keep business logic runnable locally. Cloud-specific code belongs in adapters (`backend/src/job_hunter/adapters/`) and Lambda entry points, so the same code runs in Docker Compose and on AWS.
- Describe features honestly. Mocked or unverified behaviour is labelled as such.
