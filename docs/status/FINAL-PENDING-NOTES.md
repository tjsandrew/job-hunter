# Working notes for the final pending-work document

First recorded 14 October 2026 (Singapore); authentication, resume intake, AI and cloud notes refreshed 24 October 2026 against the code. These are notes to carry into the final pending-work Markdown, not a claim that the whole product has been audited. Recheck each item against code, tests and component handoffs before marking it complete.

## Authentication and login

**Current state: Cognito sign-in is implemented and deployed to staging. Acceptance testing with real accounts is still open.**

- The web app signs in through Cognito (authorization code with PKCE) and sends bearer access tokens. The API Gateway JWT authorizer verifies them, and the API accepts a user only from the verified claims it passes on (issuer, client ID, `token_use=access`, expiry, scope). The internal user ID is derived from the issuer and subject before any database lookup.
- Accounts are created by an operator (`allow_admin_create_user_only`); there is no public sign-up. Managed login handles password reset through Cognito's built-in email sender.
- The local Alice/Casey selector sends `X-Dev-User`, which is honoured only with `AUTH_MODE=local`. The API refuses to start with `AUTH_MODE=local` unless `APP_ENV` is `local` or `test`, so a cloud deployment cannot run the development bypass.
- Ownership checks, transaction-local tenant context and PostgreSQL RLS are tested and protect resource access after identity is established.

### Work still needed

- [x] Sign-in flow with signed-out, loading and failure states (Cognito login, callback, logout).
- [x] Token handling and logout in the browser; access-token verification at the gateway and again in the API; the internal user derived from verified claims.
- [x] Production startup rejects the development authentication configuration.
- [ ] Run the complete flow with two real accounts against the deployed API: unauthorized access, expiry, logout, foreign resources, attempts to use the development header.
- [ ] Decide whether the pilot needs MFA (the Cognito Lite tier is used and MFA is off) or email verification beyond managed login.
- [ ] Show the real display name in the cloud: the identity's name is always "Job seeker".
- [ ] Clear all private UI state on logout/account switch (check in the browser).
- [ ] Invitations expire after seven days; user-evaluation participants need accounts created before they test.

## Other notes to carry forward

- **Resume intake:** PDF and Word (DOCX) upload with a review step; nothing is applied until the user accepts it. Parsing is heuristic by default and the model-based path (`BedrockModel`) is a stub that raises `MODEL_NOT_CONFIGURED`. There is no OCR, so scanned PDFs are rejected.
- **Profile bank:** implemented (items, points and alternative wordings, skills, reviewed snapshots, explicit saves, JSON export, deletion) and resume build from the bank (`/v1/documents/from-bank`). Check limitations against the design and [handoff](10-profile-bank.md).
- **AI and recommendations:** keyword/TF-IDF ranking and a semantic "For you" list built on an embedding model (the embedding worker runs in staging). Evaluation labels are assistant-only and the Bedrock embedding backend is untested. **Fit analysis is built and deployed** (design brief 12): it uses the SoCLaaS `gemma4:26b` model, its AWS worker was verified by a direct S3 test, but the web path in staging is untested because staging has no jobs, and there is no labelled accuracy set yet. The AI resume rewrite works only with fake or Ollama models, so it is unavailable in the cloud. AI cover-letter generation is not built. Unavailable UI states must stay honest.
- **Data deletion:** profile deletion exists, but durable storage-cleanup retry remains a known production gap. Audit retention/recovery across source files, confirmed versions, resumes, application packets and backups.
- **Cloud:** deployed to staging (see [deployment/README.md](../deployment/README.md)). Still to do: scheduled discovery and loading jobs into staging, security headers, measured latency/load/cost numbers, and the pause/resume and idle-behaviour acceptance checks.

## Final audit format

For each area, record: implemented behavior, remaining work, evidence/tests, release impact, and the next owner/action. Distinguish **implemented and verified**, **implemented but unverified**, **not implemented**, and **deliberately deferred**. Reconcile these notes with [PENDING.md](PENDING.md) and current component handoffs; the older pending table is not a complete final audit.
