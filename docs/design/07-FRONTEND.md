# 07 — Frontend and user journey

The web app in `apps/web/` is a single-page React app. It walks one person through the whole journey: upload a resume, discover jobs, review them, check fit, tailor documents, apply on the employer's own site, and track the result.

Opening an employer's link does not mean an application has been submitted. The tracker records only what the person chooses to record.

Read the [design README](README.md) and [contracts](CONTRACTS.md) for the API it talks to. For the resume and letter editors see [09](09-RESUME-EDITOR.md) and [14](14-COVER-LETTERS.md); for the profile page see [10](10-PROFILE-BANK.md).

## Stack and hosting

React 19 and TypeScript, built with Vite. The deployed app is a static site on **Amplify Hosting**; it calls the API Gateway endpoint directly. Locally, the same code runs on the Vite dev server against the Docker Compose stack ([LOCAL-DEVELOPMENT](../LOCAL-DEVELOPMENT.md)).

Why a plain SPA with no framework router or state library: the app has a handful of pages and one API client (`api.ts`), so hand-written routes and component state were enough. It keeps the bundle small and the behaviour easy to read.

Public build-time settings (`VITE_AUTH_MODE`, `VITE_API_BASE_URL`, `VITE_COGNITO_*`) select cloud mode. They hold no secrets.

## Sign-in

- **In AWS:** Cognito with the authorisation-code flow and PKCE, using the maintained `oidc-client-ts` library (`auth.ts`); nothing cryptographic is written by hand. There is no client secret. Tokens are kept in `sessionStorage`, renewed silently, and sent as a bearer token on every API call. Accounts are invite-only, so the sign-in page has no sign-up.
- **Locally:** two fictional development users, Alice and Casey, chosen with an `X-Dev-User` header. The backend refuses this mode unless it is started in `local` or `test` mode, so a production build cannot enable fake sign-in by accident.
- **Waking the database.** The database pauses when idle, so the first request after a quiet spell can take a few seconds. After sign-in the app shows an "Opening your workspace" screen and retries a harmless read (`GET /v1/me`) every two seconds, up to 45 seconds, before showing the app (`workspaceWake.ts`). Only that read is retried, never a write, and nothing pings the database while a tab sits open.
- **Expired sessions.** A failed silent renewal sends the person back to sign in. Saved documents are already on the server, so nothing saved is lost.

## Pages and addresses

Every page, list, listing and document has its own URL, so refresh, the back button and a pasted link all land in the same place (`routes.ts`). Unknown addresses fall back to Discover. After sign-in the app returns to the page the person was on.

| Address | Page |
|---|---|
| `/discover`, `/discover/all`, `/discover/saved`, `/discover/passed` | The job lists |
| `/jobs/<id>` | One listing, over the Discover list |
| `/profile` | Profile, profile bank, uploads and imports, job preferences |
| `/tracker` | Applications |
| `/resumes`, `/resumes/<id>` | Resume library and the resume editor |
| `/resumes/letters`, `/resumes/letters/<id>` | Cover letters and the letter editor |
| `/resumes/uploads` | The original PDF and Word files the person uploaded |

## The screens

**Discover.** Four tabs over the shared job pool: **For you** (embedding-based ranking, see [05](05-RECOMMENDATIONS.md) and [11](11-EMBEDDING-WORKER.md)), **All jobs** (keyword ranking), **Saved** and **Passed**. If For you cannot answer, the app falls back to the keyword list and says so. A filter bar offers a preset ("My preferences", "No filters" or "Custom"), a **Posted** window (default last 14 days) and **Hide expired listings** (on by default). Each card has **Save** and **Pass** buttons; Saved and Passed are lists the person can bring jobs back from.

Why buttons and not swipe cards: the original proposal had swipe gestures with buttons as a fallback. Buttons alone are accessible by keyboard and screen reader, work the same on every device, and gave the same shortlisting flow, so the gestures were never built.

**Job details.** Opening a job shows the full cleaned description, the source and any "also listed on" sources (duplicates found across sources, see [04](04-JOB-INGESTION.md)), a link to the original listing, the **Fit analysis** panel, and Save or Pass. Source links open in a new tab, and only if they are plain `http` or `https`.

**Fit analysis** (`FitPanel.tsx`). "Check my fit" starts the analysis, then the panel polls every 2.5 seconds until it is ready or failed. It shows requirements coverage with its meaning, the three groups (profile shows, not evidenced, needs your judgement) and suggestions.

A reload recovers the result from the server, so progress does not live only in React memory. See [12](12-FIT-ANALYSIS.md).

**Profile and preferences.** Upload a PDF or Word resume (up to 10 MiB), review what was extracted, edit the profile bank, and confirm the profile. Preferences cover roles, locations, work modes, seniority and minimum salary. The same preference controls appear in the Discover filters. Confirming the profile also starts embedding it so For you can rank.

**Resume Studio and letters** (`studio/`, `letters/`). The resume library, the editor with live preview, "Prepare resume" for a job, and the cover letter tab with its three starts. Autosave, review and export work as described in 09 and 06.

**Tracker.** Statuses are saved, preparing, applied, interviewing, offer, rejected and withdrawn, with notes, an applied date and an application packet. The packet holds the attached reviewed resume and cover letter as exact PDF revisions, each with its revision number. "Prepare resume" and "Prepare cover letter" open the editors for that job and return to the tracker afterwards.

**Plan and allowance** (`plan/`). The account menu shows the plan and the AI uses left this month: free users have 5, premium users 50, one use per job shared by fit analysis, AI tailoring and AI cover letters. Premium is a demo plan for now: the upgrade dialog explains this and an operator switches the account. Taking payments, for example through a payment gateway, is future work.

## Behaviour rules

- **Tokens stay out of logs and URLs.** The access token goes only in the `Authorization` header.
- **Uploads.** The app asks the API for an upload address and sends the file there with a `PUT`. In AWS the address is a presigned S3 URL, and the app then calls the finalise endpoint, which checks the bytes and extracts the text. Locally the `PUT` goes to the API itself, which finalises in the same call. Extracted text is a candidate for the person to review, never a confirmed fact.
- **Slow work is polled.** Only fit analysis is asynchronous; tailoring and letters are single requests the API answers within about 25 seconds. A failed AI request shows a plain message (for example "The AI model could not be reached") and costs no allowance.
- **Edits reset review.** Any change to a document clears its reviewed mark, and export needs the current revision to be reviewed. If the inputs a result was based on have changed, for example the profile after a fit analysis, the panel says so rather than presenting old content as fresh.
- **Unsaved changes are protected.** The app waits for autosave to finish before leaving the editor, reloading a document or opening the PDF preview. Locally, switching between Alice and Casey is blocked while a save is running and clears the previous user's lists. Whether every piece of private state clears on a cloud sign-out has not had a full two-account browser check; see [PENDING.md](../status/PENDING.md).
- **Nothing the model writes is rendered as HTML.** Extracted and generated text is shown as text.
- **Accessibility.** All main actions are real buttons or links. Dialogs close with Escape and are labelled for screen readers. The layout works on a narrow screen; the editor switches between Edit and Preview there.

## Tests

Vitest and React Testing Library (342 test definitions, which run as 371 tests; see the [README](../../README.md#tests)). The HTTP client is replaced with mocks, so the tests cover what the person sees and the requests the app makes rather than internal state. They include routing (`routes.test.ts`), sign-in (`auth.test.ts`), the wake screen (`workspaceWake.test.ts`, `WorkspaceGate.test.tsx`), Discover filters, the fit panel's polling and error states, the resume and letter editors, autosave and review gating, and the tracker.

`npm run build` type-checks and builds, and CI runs it with the tests on every push. There are no automated browser end-to-end tests; cross-user isolation and token handling are checked against the staging API by `eval/acceptance.py` (see [08](08-INTEGRATION-AND-EVALUATION.md)), and the browser-level gaps are listed in [PENDING.md](../status/PENDING.md).
