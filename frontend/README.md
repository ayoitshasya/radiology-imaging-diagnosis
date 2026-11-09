# Radiology review viewer

React viewer for the FastAPI backend in this repository: study list, study detail with
the model result and Grad-CAM overlay, reviewer decisions and the audit log.

**Educational use only. Not for clinical use.** This is not a medical device and its
output is not a diagnosis. Every page shows this notice in a banner that cannot be closed.

The viewer talks only to the FastAPI backend, never to Orthanc. It never receives or
shows patient identifiers: studies are identified by the last 12 characters of their
StudyInstanceUID, with a button that copies the full UID.

## Requirements

- Node `^22.12`, `^24` or `>=26` (the range the pinned Vitest, Vite and jsdom accept;
  developed on Node 22.13.1).
- The backend running and reachable, see below.

## Run it

From the repository root, start Orthanc and Postgres, then the API:

```
docker compose up -d
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Then, in `frontend/`:

```
npm ci
copy .env.example .env.local      (cp on macOS or Linux)
npm run dev
```

Open http://localhost:5173. Use exactly this address: the backend's CORS setting
(`backend.cors_origins` in `config.yaml`) allows only `http://localhost:5173`, and the dev
server is pinned to that host and port (`strictPort`), so `127.0.0.1:5173` is refused by
design.

If Orthanc has no studies yet, upload the demo set with
`python scripts/upload_demo_to_orthanc.py` and press **Sync from Orthanc** on the study
list.

## Environment variables

| Variable | Example | Purpose |
| --- | --- | --- |
| `VITE_API_BASE_URL` | `http://127.0.0.1:8000` | Base URL of the FastAPI backend. Required; without it every request fails with a message saying so. |

Put it in `frontend/.env.local`, which is git-ignored. `frontend/.env.example` is the
committed template. Vite builds `VITE_` variables into the page, so never put a secret in
one; the viewer needs none.

## Scripts

| Command | What it does |
| --- | --- |
| `npm run dev` | Vite dev server on http://localhost:5173 with hot reload. |
| `npm run typecheck` | `tsc -b`: TypeScript strict-mode check of the app, tests and config. |
| `npm test` | Vitest once, in jsdom, with `fetch` mocked; no backend needed. |
| `npm run test:watch` | Vitest in watch mode. |
| `npm run build` | Type check, then a production build into `frontend/dist/` (git-ignored). |
| `npm run preview` | Serve the production build locally. |

Before every commit: `npm run typecheck` and `npm test`.

## How it is organised

```
src/
  api/          client.ts (typed calls, ApiError), errors.ts (messages per status code),
                types.ts (hand-written types and field tables)
  components/   banner, layout, badges, short UID, scan and overlay, result and review panels
  hooks/        useApiData (loading, error, retry, cancellation), useObjectUrl
  pages/        study list, study detail, audit log
  review/       review validation matching the backend, in-memory reviewer name
  test/         Vitest setup and helpers (mocked API, fixtures)
```

### API types

The types in `src/api/types.ts` are written by hand rather than generated, to avoid
another dependency and to type enums as unions. They are kept in step with the backend in
two layers: each type has a field table that the compiler checks against it
(`satisfies`), and `src/api/types.test.ts` compares those tables, the endpoint list, the
enums, the length limits and the banner text with `docs/openapi.json`. After a backend
change, re-export the schema (`python scripts/export_openapi.py`) and run `npm test`.

### Errors

Every failed request becomes an `ApiError` with the HTTP status (0 when the server cannot
be reached). Pages show a short message for 404, 409, 422, 502 and 503 using the backend's
`detail`, with **Try again** where retrying can help (network, 502, 503, other 5xx). Error
bodies that are not JSON and stack traces are never shown.

### Privacy and data handling

- Images (scan and overlay) are fetched as bytes and shown through object URLs held in
  memory, released when you leave the page; nothing is written to browser storage.
- The reviewer name is remembered for the session in memory only (not localStorage,
  sessionStorage or cookies) and is gone after a reload.
- Free-text fields show "Do not enter patient names, IDs or dates." Text is cleaned and
  length-checked with the same rules as `backend/app/text.py` before it is sent.
- The audit page is read-only; the API has no routes to change the audit log.

## Troubleshooting

| You see | Likely cause |
| --- | --- |
| "Cannot reach the API server" | The backend is not running, `VITE_API_BASE_URL` is wrong, or the page was opened from an origin CORS does not allow (use http://localhost:5173). |
| "VITE_API_BASE_URL is not set" | `frontend/.env.local` is missing; copy `.env.example` and restart `npm run dev`. |
| "Service unavailable" (503) | Orthanc is down (`docker compose up -d`) or the model failed to load (see `GET /health`). |
| "Orthanc returned an error" (502) | Orthanc answered with an error, for example wrong credentials in the root `.env`. |
| Port 5173 already in use | Another dev server is running; stop it rather than changing the port, or CORS will refuse the new origin. |
