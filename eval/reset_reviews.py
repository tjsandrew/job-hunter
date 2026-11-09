"""Clear every Save/Pass decision on the evaluation accounts, so timing runs start from the same state.

The listings (All jobs, For you) leave out jobs the user has saved or passed, and the tracker lists every saved job,
so decisions left behind by a load test make later runs rank fewer jobs and list longer trackers. Each decision is
set to "none" through the API (which also removes a tracker entry the user never edited).

    python eval/reset_reviews.py            # all evaluation accounts
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cognito_tokens as ct  # noqa: E402


def call(token: str, method: str, path: str, body=None):
    request = Request(ct.API_BASE + path, method=method, data=None if body is None else json.dumps(body).encode(),
                      headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    for attempt in range(6):        # straight after a load test the gateway may still answer 429 for a while
        try:
            with urlopen(request, timeout=60) as response:
                return json.loads(response.read() or b"null")
        except HTTPError as exc:
            if exc.code not in (429, 503) or attempt == 5:
                raise
            time.sleep(2 ** attempt)


def main() -> int:
    accounts = ct.load_accounts()
    for email in sorted(accounts):
        token = ct.login(email, accounts[email]["password"])["access_token"]
        cleared = 0
        for decision in ("saved", "dismissed"):
            while True:
                page = call(token, "GET", f"/jobs/reviewed?decision={decision}&limit=100")
                items = page.get("items") or []
                if not items:
                    break
                for item in items:
                    call(token, "PUT", f"/jobs/{item['job']['id']}/review", {"decision": "none"})
                    cleared += 1
        tracker = call(token, "GET", "/applications")
        left = len(tracker.get("items", tracker)) if isinstance(tracker, dict) else len(tracker)
        print(f"{email}: cleared {cleared} decisions; tracker entries left {left}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
