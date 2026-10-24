# Documentation

| Folder | What it holds | Start with |
|---|---|---|
| [deployment/](deployment) | The staging deployment on AWS (architecture, release, costs); the original proposals are kept as history | [deployment/README.md](deployment/README.md) |
| [design/](design) | Target architecture, shared contracts and numbered component briefs (01–12) | [design/README.md](design/README.md), then [CONTRACTS.md](design/CONTRACTS.md) |
| [architecture/](architecture) | What runs where on AWS, deployed versus planned | [architecture/aws-overview.html](architecture/aws-overview.html) |
| [status/](status) | What is actually built and tested, per component, and what is still pending | [PENDING.md](status/PENDING.md) and [FEATURES.md](status/FEATURES.md) |

[WORK-SPLIT.md](WORK-SPLIT.md) shows the six work areas and where each one's code lives. [LOCAL-DEVELOPMENT.md](LOCAL-DEVELOPMENT.md) covers job imports, demo resets and local data.

The design briefs describe the intended system. The status notes record what exists. If the two disagree, the status notes describe the current code; for what runs on AWS, the [deployment guide](deployment/README.md) is the reference. The numbered handoffs in `status/` (00–13) are dated records of the work at the time and are not updated as the code changes.
