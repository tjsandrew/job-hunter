"""Access tokens for the staging evaluation accounts, without a browser.

Password sign-in (USER_PASSWORD_AUTH) is not used: those tokens lack the ``jobhunter/use`` scope the API
requires. Instead this performs the same authorization-code + PKCE sign-in the web app uses, against the
classic managed login page of our own user pool, then exchanges the code for tokens. Refresh tokens last
one day; ``refresh`` turns one into a fresh access token (valid 60 minutes).

Account passwords live in ~/.job-hunter-eval/accounts.json (mode 600, outside the repository).
Tokens and passwords are never printed.
"""
from __future__ import annotations

import base64
import hashlib
import html.parser
import http.cookiejar
import json
import os
import secrets
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, Request, build_opener

# Public staging values (also published as GitHub repository variables).
COGNITO_DOMAIN = os.environ.get("EVAL_COGNITO_DOMAIN", "https://jobhunter-staging-091512051916.auth.ap-southeast-1.amazoncognito.com")
CLIENT_ID = os.environ.get("EVAL_COGNITO_CLIENT_ID", "51vrsmknb2tfil8rhgim8iutt5")
REDIRECT_URI = os.environ.get("EVAL_REDIRECT_URI", "https://main.d3u7qeowlfzmzj.amplifyapp.com/auth/callback")
API_BASE = os.environ.get("EVAL_API_BASE", "https://izjy1rpw2d.execute-api.ap-southeast-1.amazonaws.com/v1")
SCOPE = "openid email profile jobhunter/use"
ACCOUNTS_FILE = Path.home() / ".job-hunter-eval" / "accounts.json"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _CsrfParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.csrf = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "input" and values.get("name") == "_csrf":
            self.csrf = values.get("value")


def load_accounts() -> dict[str, dict]:
    return json.loads(ACCOUNTS_FILE.read_text())


def _post_form(url: str, fields: dict, opener=None) -> dict:
    request = Request(url, data=urlencode(fields).encode(), method="POST",
                      headers={"Content-Type": "application/x-www-form-urlencoded"})
    with (opener or build_opener()).open(request, timeout=30) as response:
        return json.load(response)


def login(email: str, password: str) -> dict:
    """Sign in through the managed login page; returns the token response (access, id, refresh)."""
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    query = urlencode({"response_type": "code", "client_id": CLIENT_ID, "redirect_uri": REDIRECT_URI,
                       "scope": SCOPE, "state": secrets.token_urlsafe(16),
                       "code_challenge": challenge, "code_challenge_method": "S256"})
    jar = http.cookiejar.CookieJar()
    browser = build_opener(HTTPCookieProcessor(jar))
    # /oauth2/authorize redirects to /login, which sets the XSRF cookie and renders the form.
    with browser.open(f"{COGNITO_DOMAIN}/login?{query}", timeout=30) as response:
        parser = _CsrfParser()
        parser.feed(response.read().decode("utf-8", "replace"))
    if not parser.csrf:
        raise RuntimeError("managed login page had no CSRF field; has the login page version changed?")
    submit = build_opener(HTTPCookieProcessor(jar), _NoRedirect())
    form = urlencode({"_csrf": parser.csrf, "username": email, "password": password, "signInSubmitButton": "Sign in"})
    try:
        submit.open(Request(f"{COGNITO_DOMAIN}/login?{query}", data=form.encode(), method="POST",
                            headers={"Content-Type": "application/x-www-form-urlencoded"}), timeout=30)
        raise RuntimeError("sign-in did not redirect: wrong password or a required challenge")
    except HTTPError as redirect:
        if redirect.code not in (301, 302, 303):
            raise
        location = redirect.headers.get("Location", "")
    code = parse_qs(urlparse(location).query).get("code", [None])[0]
    if not code:
        raise RuntimeError("sign-in redirect carried no authorization code (wrong password?)")
    return _post_form(f"{COGNITO_DOMAIN}/oauth2/token", {
        "grant_type": "authorization_code", "client_id": CLIENT_ID, "code": code,
        "redirect_uri": REDIRECT_URI, "code_verifier": verifier})


def refresh(refresh_token: str) -> str:
    """A fresh access token from a refresh token (the refresh token itself is not rotated)."""
    return _post_form(f"{COGNITO_DOMAIN}/oauth2/token", {
        "grant_type": "refresh_token", "client_id": CLIENT_ID, "refresh_token": refresh_token})["access_token"]


def access_tokens() -> dict[str, str]:
    """Sign every stored account in and return {email: access_token}."""
    return {email: login(email, account["password"])["access_token"] for email, account in load_accounts().items()}


if __name__ == "__main__":
    import sys
    from urllib.request import urlopen

    for email, account in load_accounts().items():
        tokens = login(email, account["password"])
        request = Request(f"{API_BASE}/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
        try:
            with urlopen(request, timeout=60) as response:
                me = json.load(response)
            print(f"{email}: signed in; /me -> plan={me.get('plan')} refresh_token={'yes' if tokens.get('refresh_token') else 'no'}")
        except HTTPError as exc:
            print(f"{email}: signed in but /me returned HTTP {exc.code}", file=sys.stderr)
