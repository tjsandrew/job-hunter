"""Locust load tests against staging (system evaluation B1 and B3).

User classes:
* BaselineUser  (B1): one user cycling evenly through the browse endpoints, for per-endpoint percentiles.
* BrowsingUser  (B3): a weighted browsing session (Discover, For you, job details, tracker, Save/Pass).

Set EVAL_STEPS (e.g. "1,10,50,100") to run BrowsingUser as a step load; EVAL_STEP_SECONDS sets each step's
length (default 300) and EVAL_SPAWN_RATE the users started per second (default 5).

Failures are labelled by kind so Locust's failure table separates the deliberate caps from errors:
"429 throttled", "5xx server error", "401 auth", "HTTP <code>". AI endpoints are never called: they spend the
monthly allowance and a shared model key.

Examples (from the repository root, evaluation virtualenv):
    locust -f eval/locustfile.py BaselineUser --headless -u 1 -r 1 -t 10m --csv eval/results/b1-baseline
    EVAL_STEPS=1,10,50,100 locust -f eval/locustfile.py BrowsingUser --headless --csv eval/results/b3-run1 --csv-full-history
Announce load tests in the team chat first, and never run them during a user-testing session.
"""
from __future__ import annotations

import itertools
import os
import random
import sys
import threading
import time
from pathlib import Path

from locust import HttpUser, LoadTestShape, between, constant, events, task

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cognito_tokens as ct  # noqa: E402

API_PATH = "/v1"
TOKEN_LIFETIME_SECONDS = 50 * 60     # access tokens last 60 minutes; refresh well before
# Token age uses the wall clock: the monotonic clock stops while the laptop sleeps, but token expiry does not.


class Account:
    """One evaluation account, its refresh token and a shared, thread-safe access token."""

    def __init__(self, email: str, password: str):
        tokens = ct.login(email, password)
        self.email = email
        self._refresh = tokens["refresh_token"]
        self._access = tokens["access_token"]
        self._issued = time.time()
        self._lock = threading.Lock()

    def token(self) -> str:
        with self._lock:
            if time.time() - self._issued > TOKEN_LIFETIME_SECONDS:
                self._access = ct.refresh(self._refresh)
                self._issued = time.time()
            return self._access


_accounts: list[Account] = []
_next_account = None
_signin_seconds = 0.0   # excluded from the first load step


@events.test_start.add_listener
def sign_in_accounts(environment, **_):
    global _next_account, _signin_seconds
    if not _accounts:
        started = time.monotonic()
        _accounts.extend(Account(email, account["password"]) for email, account in sorted(ct.load_accounts().items()))
        _next_account = itertools.cycle(_accounts)
        _signin_seconds = time.monotonic() - started
        print(f"signed in {len(_accounts)} evaluation accounts in {_signin_seconds:.1f}s")


def _classify(response) -> None:
    code = response.status_code
    if 200 <= code < 300:
        response.success()
    elif code == 429:
        response.failure("429 throttled")
    elif code >= 500:
        response.failure("5xx server error")
    elif code == 401:
        response.failure("401 auth")
    else:
        response.failure(f"HTTP {code}")


class ApiUser(HttpUser):
    abstract = True
    host = ct.API_BASE.removesuffix(API_PATH)

    def on_start(self):
        self.account = next(_next_account)
        self.job_ids: list[str] = []

    def _request(self, method: str, path: str, name: str, json_body=None):
        headers = {"Authorization": f"Bearer {self.account.token()}"}
        with self.client.request(method, API_PATH + path, name=name, headers=headers, json=json_body,
                                 catch_response=True) as response:
            _classify(response)
            return response

    def _remember_jobs(self, response) -> None:
        try:
            items = response.json().get("items") or []
        except ValueError:
            return
        ids = [str((item.get("job") or item).get("id")) for item in items if (item.get("job") or item).get("id")]
        if ids:
            self.job_ids = ids

    def all_jobs(self):
        offset = random.choice((0, 0, 20, 40))
        self._remember_jobs(self._request("GET", f"/recommendations?limit=20&offset={offset}", "/recommendations"))

    def for_you(self):
        self._remember_jobs(self._request("GET", "/recommendations/for-you?limit=20", "/recommendations/for-you"))

    def job_detail(self):
        if not self.job_ids:
            self.all_jobs()
        if self.job_ids:
            self._request("GET", f"/jobs/{random.choice(self.job_ids)}", "/jobs/{id}")


class BrowsingUser(ApiUser):
    """B3: a person browsing Discover and the tracker, with occasional Save/Pass decisions."""

    wait_time = between(1, 3)

    @task(1)
    def me(self):
        self._request("GET", "/me", "/me")

    @task(3)
    def discover_all(self):
        self.all_jobs()

    @task(3)
    def discover_for_you(self):
        self.for_you()

    @task(3)
    def open_job(self):
        self.job_detail()

    @task(1)
    def saved_jobs(self):
        self._request("GET", "/jobs/reviewed?decision=saved&limit=20", "/jobs/reviewed")

    @task(1)
    def tracker(self):
        self._request("GET", "/applications", "/applications")

    @task(1)
    def profile(self):
        self._request("GET", "/profile/bank", "/profile/bank")

    @task(1)
    def save_or_pass(self):
        if not self.job_ids:
            self.all_jobs()
        if self.job_ids:
            decision = random.choice(("saved", "dismissed"))
            self._request("PUT", f"/jobs/{random.choice(self.job_ids)}/review", "PUT /jobs/{id}/review",
                          {"decision": decision})


class BaselineUser(ApiUser):
    """B1: cycle the browse endpoints evenly so each gets the same number of samples."""

    # One request at a time; EVAL_WAIT is the pause between them (B1 used 0.1 s).
    wait_time = constant(float(os.environ.get("EVAL_WAIT", "0.5")))
    _cycle = ("me", "all_jobs", "for_you", "job_detail", "reviewed", "applications", "profile", "profile_bank", "documents")

    def on_start(self):
        super().on_start()
        self._steps = itertools.cycle(self._cycle)

    @task
    def next_endpoint(self):
        step = next(self._steps)
        if step in ("all_jobs", "for_you", "job_detail"):
            getattr(self, step)()
            return
        path = {"me": "/me", "reviewed": "/jobs/reviewed?decision=saved&limit=20", "applications": "/applications",
                "profile": "/profile", "profile_bank": "/profile/bank", "documents": "/documents"}[step]
        self._request("GET", path, path.split("?")[0])


if os.environ.get("EVAL_STEPS"):
    class StepLoad(LoadTestShape):
        """1 -> 10 -> 50 -> 100 users (EVAL_STEPS), each held for EVAL_STEP_SECONDS, then stop."""

        steps = [int(value) for value in os.environ["EVAL_STEPS"].split(",")]
        step_seconds = int(os.environ.get("EVAL_STEP_SECONDS", "300"))
        spawn_rate = float(os.environ.get("EVAL_SPAWN_RATE", "5"))

        def tick(self):
            index = int(max(0.0, self.get_run_time() - _signin_seconds) // self.step_seconds)
            if index >= len(self.steps):
                return None
            return self.steps[index], self.spawn_rate
