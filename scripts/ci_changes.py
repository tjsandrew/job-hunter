"""Select PR checks from Git paths; main retains full app/script checks."""
import json
import os
from pathlib import Path
import re
import subprocess


def changed_paths(base):
    if not re.fullmatch(r"[a-f0-9]{40}", base or "") or base == "0" * 40:
        return None  # Initial/unknown history: run everything, never skip unsafely.
    try:
        # Report both sides of cross-component renames as delete/add paths.
        result = subprocess.run(["git", "diff", "--no-renames", "--name-only", "-z", base, "HEAD"], check=True, capture_output=True)
    except subprocess.CalledProcessError:
        return None
    return result.stdout.decode().split("\0")[:-1]


def select_checks(paths, event):
    if paths is None:
        return dict.fromkeys(("web", "backend", "package", "scripts", "embedder"), True)
    workflow = any(path.startswith(".github/workflows/") for path in paths)
    backend = any(path.startswith(("backend/", "contracts/")) or path in {
        "compose.yaml", "Makefile", "scripts/smoke.py", "scripts/check_profile_bank_migration.py", "scripts/schema_0009_columns.json"
    } for path in paths)
    return {
        "web": event == "push" or workflow or any(path.startswith(("apps/web/", "contracts/")) for path in paths),
        "backend": event == "push" or workflow or backend,
        "package": workflow or any(path.startswith("backend/") for path in paths),
        "scripts": event == "push" or workflow or any(path.startswith("scripts/") or path == "backend/requirements.lock" for path in paths),
        # The embedder is its own service (own tests, own images); only its folder affects it.
        "embedder": event == "push" or workflow or any(path.startswith("services/embedder/") for path in paths),
    }


def main():
    event_name = os.environ["GITHUB_EVENT_NAME"]
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    base = event.get("pull_request", {}).get("base", {}).get("sha") if event_name == "pull_request" else event.get("before")
    selected = select_checks(changed_paths(base), event_name)
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        for job, enabled in selected.items():
            output.write(f"{job}={str(enabled).lower()}\n")


if __name__ == "__main__":
    main()
