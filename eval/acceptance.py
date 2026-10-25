"""Acceptance checks on staging (plan step A6): cross-user isolation and token handling.

Account B (jh-eval-02) creates a resume document, a pending upload, a Save decision and a fit-analysis request.
Account A (jh-eval-01) then tries to read, change, delete and attach them by ID; every attempt must fail with
404 and B's data must never appear in A's lists. Token checks cover missing, tampered and ID tokens, the local
development header, and what revoking a refresh token does. B's test document and upload are deleted afterwards.

Writes evidence (no tokens) to eval/results/a6-acceptance-<UTC time>.json and prints a PASS/FAIL table.
Uses one of B's five monthly AI uses (the fit-analysis request).
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cognito_tokens as ct  # noqa: E402

RESULTS = Path(__file__).resolve().parent / "results"
checks: list[dict] = []


def call(token: str | None, method: str, path: str, body=None, headers=None):
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    if token:
        request_headers["Authorization"] = f"Bearer {token}"
    request = Request(ct.API_BASE + path, method=method, headers=request_headers,
                      data=None if body is None else json.dumps(body).encode())
    try:
        with urlopen(request, timeout=60) as response:
            raw = response.read()
            return response.status, (json.loads(raw) if raw[:1] in (b"{", b"[") else None)
    except HTTPError as exc:
        return exc.code, None


def check(group: str, name: str, passed: bool, detail: str) -> None:
    checks.append({"group": group, "check": name, "result": "PASS" if passed else "FAIL", "detail": detail})


def expect_status(group: str, name: str, token, method: str, path: str, expected: set[int], body=None, headers=None):
    status, payload = call(token, method, path, body, headers)
    check(group, name, status in expected, f"{method} {path.split('?')[0]} -> {status} (expected {sorted(expected)})")
    return status, payload


def items_of(payload) -> list:
    """List endpoints return either a bare list or {"items": [...]}; anything else is an error."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        return payload["items"]
    raise RuntimeError(f"unexpected list response: {type(payload).__name__}")


def ids(payload, key="id") -> set[str]:
    found = set()
    for item in items_of(payload):
        source = (item.get("job") or item) if key == "job" else item
        found.add(str(source.get("id")))
    return found


def main() -> int:
    accounts = ct.load_accounts()
    email_a, email_b = "jh-eval-01@example.com", "jh-eval-02@example.com"
    a = ct.login(email_a, accounts[email_a]["password"])
    b = ct.login(email_b, accounts[email_b]["password"])
    token_a, token_b = a["access_token"], b["access_token"]
    me_a, me_b = call(token_a, "GET", "/me")[1], call(token_b, "GET", "/me")[1]
    check("setup", "accounts are distinct users", me_a["user_id"] != me_b["user_id"], "two different internal user IDs")

    # ---- B creates data ------------------------------------------------------------------------------------
    _, doc = call(token_b, "POST", "/documents", {"title": "A6 isolation test (fictional)", "content": {
        "name": "Arjun Nair (fictional)", "sections": []}})
    _, bank_b = call(token_b, "GET", "/profile/bank")
    item_b = bank_b["items"][0]
    _, upload = call(token_b, "POST", "/uploads", {"filename": "a6-test.pdf", "content_type": "application/pdf",
                                                  "size_bytes": 1024})
    upload_id = (upload or {}).get("id") or (upload or {}).get("upload_id")
    reviewed_a = set()
    for decision in ("saved", "dismissed"):
        reviewed_a |= ids(call(token_a, "GET", f"/jobs/reviewed?{urlencode({'decision': decision, 'limit': 100})}")[1], "job")
    jobs = items_of(call(token_b, "GET", "/recommendations?limit=100")[1])
    job_id = next(str((j.get("job") or j)["id"]) for j in jobs if str((j.get("job") or j)["id"]) not in reviewed_a)
    call(token_b, "PUT", f"/jobs/{job_id}/review", {"decision": "saved"})
    fit_status, fit = call(token_b, "POST", f"/jobs/{job_id}/fit-analysis", {})
    fit_id = (fit or {}).get("id")
    check("setup", "B created a document, upload, Save and fit request",
          bool(doc and upload_id and fit_id), f"document={bool(doc)} upload={bool(upload_id)} fit={fit_status}")

    # ---- A against B's resources ---------------------------------------------------------------------------
    group = "isolation"
    doc_id, item_id = doc["id"], item_b["id"]
    expect_status(group, "A cannot read B's document", token_a, "GET", f"/documents/{doc_id}", {404})
    expect_status(group, "A cannot preview B's document PDF", token_a, "GET", f"/documents/{doc_id}/preview.pdf", {404})
    expect_status(group, "A cannot edit B's document", token_a, "PATCH", f"/documents/{doc_id}", {404},
                  {"title": "hijacked", "expected_revision": doc["revision"]})
    expect_status(group, "A cannot duplicate B's document", token_a, "POST", f"/documents/{doc_id}/duplicate", {404}, {})
    expect_status(group, "A cannot review B's document", token_a, "POST", f"/documents/{doc_id}/review", {404},
                  {"expected_revision": doc["revision"]})
    expect_status(group, "A cannot delete B's document", token_a, "DELETE", f"/documents/{doc_id}", {404})
    expect_status(group, "A cannot read B's profile item", token_a, "GET", f"/profile/items/{item_id}", {404})
    expect_status(group, "A cannot edit B's profile item", token_a, "PATCH", f"/profile/items/{item_id}", {404},
                  {"expected_revision": item_b.get("revision", 1), "tags": ["hijacked"]})
    expect_status(group, "A cannot delete B's profile item", token_a, "DELETE", f"/profile/items/{item_id}", {404})
    if upload_id:
        expect_status(group, "A cannot read B's upload", token_a, "GET", f"/uploads/{upload_id}", {404})
        expect_status(group, "A cannot download B's upload", token_a, "GET", f"/uploads/{upload_id}/download", {404})
        expect_status(group, "A cannot delete B's upload", token_a, "DELETE", f"/uploads/{upload_id}", {404})
    if fit_id:
        expect_status(group, "A cannot read B's fit analysis", token_a, "GET", f"/fit-analyses/{fit_id}", {404})
    status, app = call(token_a, "PUT", f"/applications/{job_id}", {"status": "saved", "resume_document_id": doc_id,
                                                                   "expected_resume_revision": doc["revision"]})
    attached = bool(app) and str(app.get("resume_document_id")) == str(doc_id)
    check(group, "A cannot attach B's resume to A's application", status >= 400 and not attached,
          f"PUT /applications/{{job}} with B's document -> {status}")

    lists = {
        "documents": ids(call(token_a, "GET", "/documents")[1]),
        "saved jobs": ids(call(token_a, "GET", "/jobs/reviewed?decision=saved&limit=100")[1], "job"),
        "fit analyses": ids(call(token_a, "GET", "/fit-analyses")[1]),
    }
    check(group, "B's document is not in A's list", doc_id not in lists["documents"], "GET /documents")
    check(group, "B's Save is not in A's saved jobs", job_id not in lists["saved jobs"], "GET /jobs/reviewed")
    check(group, "B's fit analysis is not in A's list", str(fit_id) not in lists["fit analyses"], "GET /fit-analyses")
    still_b = call(token_b, "GET", f"/documents/{doc_id}")[0] == 200 and call(token_b, "GET", f"/profile/items/{item_id}")[0] == 200
    check(group, "B's data is unchanged after A's attempts", still_b, "B can still read its document and item")

    # ---- tokens --------------------------------------------------------------------------------------------
    group = "tokens"
    expect_status(group, "no token is rejected", None, "GET", "/me", {401})
    tampered = token_a[:-6] + ("AAAAAA" if not token_a.endswith("AAAAAA") else "BBBBBB")
    expect_status(group, "tampered signature is rejected", tampered, "GET", "/me", {401})
    expect_status(group, "ID token is rejected (not an access token)", a["id_token"], "GET", "/me", {401, 403})
    expect_status(group, "development header without a token is rejected", None, "GET", "/me", {401},
                  headers={"X-Dev-User": "alice"})
    _, spoof = call(token_a, "GET", "/me", headers={"X-Dev-User": "casey"})
    check(group, "development header cannot switch user", (spoof or {}).get("user_id") == me_a["user_id"],
          "A's token with X-Dev-User: casey still returns A")

    session = ct.login(email_a, accounts[email_a]["password"])
    revoke = Request(f"{ct.COGNITO_DOMAIN}/oauth2/revoke", method="POST",
                     data=urlencode({"token": session["refresh_token"], "client_id": ct.CLIENT_ID}).encode(),
                     headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urlopen(revoke, timeout=30) as response:
        revoked = response.status == 200
    try:
        ct.refresh(session["refresh_token"])
        refresh_after_revoke = "accepted"
    except HTTPError as exc:
        refresh_after_revoke = f"rejected ({exc.code})"
    check(group, "revoked refresh token cannot get new access tokens", revoked and refresh_after_revoke != "accepted",
          f"revoke -> {200 if revoked else 'error'}; refresh -> {refresh_after_revoke}")
    status = call(session["access_token"], "GET", "/me")[0]
    checks.append({"group": group, "check": "access token after its refresh token is revoked",
                   "result": "INFO", "detail": f"GET /me -> {status}. API Gateway's JWT authorizer is stateless, so a "
                   "revoked session's access token keeps working until it expires (60 minutes)."})

    # ---- cleanup -------------------------------------------------------------------------------------------
    call(token_b, "DELETE", f"/documents/{doc_id}")
    if upload_id:
        call(token_b, "DELETE", f"/uploads/{upload_id}")

    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = RESULTS / f"a6-acceptance-{stamp}.json"
    out.write_text(json.dumps({"run_at": stamp, "api": ct.API_BASE, "accounts": [email_a, email_b],
                               "checks": checks}, indent=2))
    width = max(len(c["check"]) for c in checks)
    for c in checks:
        print(f"{c['result']:4}  {c['group']:9}  {c['check']:{width}}  {c['detail']}")
    failed = [c for c in checks if c["result"] == "FAIL"]
    print(f"\n{len(checks) - len(failed)} of {len(checks)} passed or informational; results in {out.relative_to(Path.cwd())}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
