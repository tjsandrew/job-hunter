# Contributing

## Workflow

1. Pull the latest `main` and create a branch: `git checkout -b <your-name>/<short-topic>`.
2. Keep changes within your area from the [work split](docs/deployment/SIX-PERSON-WORK-SPLIT.md). Agree changes to shared contracts ([docs/design/CONTRACTS.md](docs/design/CONTRACTS.md)) with the affected owners first.
3. Add or update tests with the code, and run the checks in the [README](README.md#running-the-checks).
4. Open a pull request into `main`. CI must pass, and one teammate should review it before merging.
5. When you finish a component milestone, update its note in [docs/status/](docs/status) with the commands you ran, test results and remaining gaps.

## Rules

- **No secrets or private data in Git.** Do not commit `.env` files, AWS keys, real resumes, or course and report files. Use `.env.example` for configuration names only. Use synthetic fixtures for tests.
- **Do not provision paid AWS resources** unless the team has agreed to it. Record what you create and how to tear it down.
- Keep business logic runnable locally. Cloud-specific code belongs in adapters and entry points, following [LOCAL-TO-AWS.md](docs/deployment/LOCAL-TO-AWS.md).
- Describe features honestly. Mocked or unverified behaviour is labelled as such.
