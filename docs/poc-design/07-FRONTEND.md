# 07 — Frontend and complete user journey

**Resume editor requirement:** [09-RESUME-EDITOR.md](09-RESUME-EDITOR.md) adds a core local resume editor, manual resume creation, template/layout controls, preview, autosave and PDF export. Its document/API extensions supersede assumptions that every resume requires AI generation or a job.

**Current delivery scope:** [local application first; AWS-native services later](DELIVERY-SCOPE.md). This staging rule overrides earlier cloud requirements for the local milestone.

**Portability requirement:** follow [LOCAL-TO-AWS.md](LOCAL-TO-AWS.md). Keep this component’s logic shared between local Docker execution and AWS; record adapter differences and unverified cloud checks in its handoff.

Read [README](README.md) and [contracts](CONTRACTS.md). Own `apps/web/`. Use generated API types and contract fixtures; do not invent backend state transitions. No wireframe deliverable is required.

## Screens

| Screen | Required interactions and states |
|---|---|
| Sign in | Cognito code + PKCE, logout, expired-session recovery; no client secret |
| Profile/resume | Upload, processing progress, parse errors/manual entry, editable extracted facts, explicit confirmation, embedding pending/ready |
| Preferences | Role/location/work mode/seniority/salary inputs, unknown-value policy, saved-state/error feedback |
| Discover | Swipe cards plus Save/Dismiss buttons and keyboard access; matching evidence, source freshness, fixture/fallback indicators, empty state |
| Job details | Full cleaned description, source application link, explicit required documents, Save and Prepare actions |
| Preparation | Fit strengths/gaps/evidence; Generate CV/cover letter; task states; allowance explanation; editable drafts, review revision and export |
| Application tracker | Saved/preparing/applied/interviewing/offer/rejected/withdrawn, editable notes/dates, links to documents/job source |

Preserve the report's journey: upload → discover → review → assess fit → tailor → review/apply externally → track. Opening an employer link does not mean an application has been submitted.

## Behaviour contracts

- Use access tokens on API calls; keep them out of logs and URLs. Use a maintained Cognito/OIDC client for PKCE/state/nonce/token lifecycle. Do not implement cryptography manually.
- Upload using the presigned POST fields, then call completion. Display supported file limits before upload.
- Poll owned tasks initially every two seconds, backing off to five/ten seconds. Stop on terminal states, pause when hidden and resume when visible. A refresh recovers tasks from server state; do not rely only on React memory.
- Explain `queued`, `running`, `retry_wait`, success and terminal failure. Only offer Retry when the API marks it retryable. Disable repeated submissions while pending but also send stable idempotency keys.
- Show the server's allowance summary as distinct jobs/month. Technical errors should not appear as a purchase demand. Premium is a demonstration entitlement, not a fake payment flow.
- If inputs change after generation, display the versions used. Do not label old content as refreshed. Manual edits reset review; export requires reviewing that revision.
- Sanitize/render extracted text safely. Do not render raw model HTML. Source links use safe protocols and external-link behaviour.
- Support keyboard navigation, focus states, readable loading/error messages and a usable small-screen layout. Swipe is an enhancement to explicit controls.

## Unit and component tests required during implementation

Use Vitest and React Testing Library with contract-shaped HTTP mocks (for example MSW). Test forms and validation, upload-completion sequencing, task-state rendering, polling/backoff/stop behaviour with fake timers, session-expiry handling, allowance messages, input-version warnings, edit/review/export gating and optimistic-review rollback. Verify Save/Dismiss buttons and swipe gestures produce equivalent requests, and that controls work through keyboard interaction.

Test user-visible behaviour and requests rather than internal hook state or large DOM snapshots. Keep Playwright browser journey tests separate; mocked UI tests do not establish real authentication or backend isolation.

## Development and acceptance

Build with contract fixtures and mocked HTTP first; a visible dev indicator distinguishes mocks. The production build must not enable fake authentication or fixture inference accidentally.

Acceptance: a new user completes all screens; a second account cannot see the first account's content; uploads/errors/retries/empty recommendations work; swipe and buttons have equivalent effects; tracking survives reload; an edited/reviewed CV and cover letter download correctly; session expiry does not lose saved drafts. Include end-to-end browser tests for the main journey and failure recovery, plus a production build/type check.

Handoff lists actual run/build commands, required public environment values, tested viewports and remaining API dependencies.
