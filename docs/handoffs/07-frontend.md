# Frontend handoff

## Delivered

Implemented the React, TypeScript and Vite app in `apps/web/` with a real `/v1` API client and a development identity selector (`alice` / `bob`, sent as `X-Dev-User`). The UI includes Discover, Profile and preferences, Application Tracker, and Resume Studio. The app has responsive navigation, accessible names for icon-only controls, loading/error/empty states, search and status filters, and clearly labelled AI unavailability.

Discover renders the backend's observed job facts, reason strings and source links. Search runs on the server and uses offset pagination with a Load more action, so filtering applies across the full result pool instead of only the first 20 cards. It does not turn ranking scores into match percentages or invent work mode, salary, employment type, posting date or freshness. Saving/passing a job calls the review route; saved jobs are then reloaded into tracking. Tracking status, notes and application date use the owned application endpoint.

Resume Studio supports manual resume creation, two templates, editable contact details, summary, sections, entries and bullets, section/entry removal and section reordering, bounded type size and margins, undo/redo, 700 ms debounced autosave, conflict/error state with local content retained, duplication, revision review and reviewed-only PDF export. If the user keeps typing during a slow save, the accepted server revision is applied underneath the newer local draft and that draft is saved against the returned revision. Its responsive preview pane shows the structured document; a separate server-rendered PDF preview opens in an in-app dialog. Profile accepts PDFs up to 10 MiB, displays extracted text in a read-only review candidate, and leaves all profile facts for the user to enter and confirm.

## Run and configuration

```sh
cd apps/web
npm ci
npm run dev
```

Vite listens on `0.0.0.0:5173`. The default `/v1` proxy targets `http://localhost:8000`; set `API_PROXY_TARGET=http://api:8000` for Docker Compose. Set `VITE_API_BASE_URL` only when the browser should call a different public API base. The supplied `Dockerfile` uses Node 22, `npm ci`, and the Vite dev server. Dependencies are pinned in `package.json` and `package-lock.json`.

## API calls

The client consumes `/me`, `/profile`, `/profile/confirm`, `/preferences`, searchable and paginated `/recommendations?q=&offset=&limit=`, `/jobs/{id}/review`, `/applications`, `/documents?kind=resume`, document create/patch/duplicate/review/export, `/documents/{id}/preview.pdf`, `/exports/{id}`, and the `/uploads` → `/uploads/{id}/content` → `/uploads/{id}` extraction flow. Requests are snake_case, use `X-Dev-User` in the local app, and surface API error messages. PDF requests go through `fetch` with the same identity header.

The app does not implement Cognito login, AI generation, upload parsing into profile facts, or a job-detail route. Local recommendation filtering uses role and location preferences; salary, seniority and work-mode filtering are identified as planned. Resume preview's in-app layout is explicitly approximate; the server PDF view is the render to inspect. Keyboard accessible controls are used throughout, but automated browser coverage remains separate from these component tests.

## Checks

- `npm test -- --reporter=dot` — 10 Vitest / React Testing Library tests pass, including server search/pagination, upload candidate review, blank resume creation, profile save gating, edit primitives, autosave conflict retention, slow-save rebase, export gating and refusal to switch identity while a save is dirty.
- `npm run build` — TypeScript check and Vite production build pass.
- Parent agent visually inspected the app at desktop and narrow viewports; the narrow preview toggle and mobile account switcher were adjusted after that review.

## Notes for integration

Backend should return `source`, `source_board`, `source_url`/`url`, `posted_at` and `fetched_at` so the UI can label source and dates from available evidence. Missing locations are displayed as “Location not specified”; unavailable optional facts are omitted. `GET /uploads/{id}` extraction polling is not currently in the UI because extraction is unavailable in the local backend. Confirm the Compose proxy is set to `http://api:8000` when the frontend container is used.
