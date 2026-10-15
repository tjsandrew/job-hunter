# Working notes for the final pending-work document

Recorded 14 October 2026 (Singapore). These are notes to carry into the final pending-work Markdown after implementation, not a claim that the whole product has been audited. Recheck each item against code, tests and component handoffs before marking it complete.

## Authentication and login — explicit release blocker

**Current state: real login is not implemented.**

- The local Alice/Casey selector sends `X-Dev-User`; the backend accepts those demo identities and maps them to internal user IDs.
- No login/signup flow, JWT issuance or JWT verification is implemented. We are not simulating a JWT flow.
- Ownership checks, transaction-local tenant context and PostgreSQL RLS are real and tested. These protect resource access after the development identity is selected; they are not proof of real-user authentication.
- Local authentication is gated to local/test mode. This safeguard does not substitute for implementing production authentication.
- The target design uses Cognito with authorization-code/PKCE and access-token verification. Implementation and real AWS validation remain pending.

### Work still needed

- [ ] Implement the chosen real sign-in/account setup flow, with clear signed-out, loading, failure and recovery states.
- [ ] Implement session/token handling, expiry/refresh and logout; decide whether the pilot needs email verification/password recovery or equivalent provider-managed flows.
- [ ] Verify access-token signature and trusted issuer/client audience/scope/token type as required by the shared auth contract. Reject expired/invalid tokens and inappropriate ID tokens.
- [ ] Derive the internal user/tenant from verified identity claims. Remove reliance on `X-Dev-User` outside the explicit development mode.
- [ ] Provision/map new users safely and idempotently; clear all private UI state on logout/account switch.
- [ ] Exercise the complete flow against the real provider and deployed API, including unauthorized access, expiry, logout, foreign resources and attempts to use the development bypass.
- [ ] Confirm production startup/deployment rejects development authentication configuration.

### Wording to retain in the final document

> The local prototype uses development-only Alice/Casey identities through an allowlisted header. Real login, JWT verification and session handling remain pending. Ownership checks and database tenant isolation are implemented, but production authentication must be completed and validated before a real-user release.

Keep this in a prominent authentication/release-blockers section. Do not bury it solely under “AWS setup” or imply that local feature completion means login is complete.

## Other notes to carry forward

- **Resume intake:** current local intake extracts PDF text only (10 MiB/20-page limits); it does not perform OCR or model-based structured intake. The profile bank import parser/review/apply flow is the next implementation step. Disabled Import controls are intentional.
- **Profile bank:** steps 1–2 are implemented. Remaining bank-to-resume assembly/editor integration, later features and any limitations must be checked against the design and [handoff](10-profile-bank.md).
- **AI and recommendations:** local keyword/TF-IDF ranking exists. Real semantic embeddings, AI fit analysis and AI preparation are separate pending integrations; unavailable UI states must stay honest.
- **Data deletion:** profile deletion exists, but durable storage-cleanup retry remains a known production gap. Audit retention/recovery across source files, confirmed versions, resumes, application packets and backups.
- **Cloud:** real Cognito, S3, SQS/Lambda task behavior, RDS operations, Bedrock, deployment/observability and cost/performance validation remain separate from successful local tests.

## Final audit format

For each area, record: implemented behavior, remaining work, evidence/tests, release impact, and the next owner/action. Distinguish **implemented and verified**, **implemented but unverified**, **not implemented**, and **deliberately deferred**. Reconcile these notes with [PENDING.md](PENDING.md) and current component handoffs; the older pending table is not a complete final audit.
