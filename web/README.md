# Live Sound Radar — React dashboard

React + TypeScript dashboard for Live Sound Radar. It polls the local FastAPI
service, presents live detections (**Possible knocking** / **Possible doorbell**)
and event history, and exposes listening, acknowledgement, privacy, speech, and
retention controls.

The dashboard never calls ElevenLabs, Snowflake, or any cloud provider directly;
it talks to the local backend through same-origin `/v1` paths only.

## Stack

- React 19 + TypeScript
- Vite 8
- Tailwind CSS 4 + shadcn/ui and Radix primitives
- Vitest + Testing Library + jsdom
- ESLint

## Requirements

- Node.js 24 LTS and npm

## Setup and run

From `web`:

```bash
npm ci
npm run dev
```

Open <http://127.0.0.1:5173>.

## Mock vs live API

`VITE_USE_MOCK_API` selects where the dashboard gets its data:

```bash
# Dashboard only: contract-valid mock data, no TensorFlow/YAMNet/microphone needed.
VITE_USE_MOCK_API=true npm run dev

# Real local backend on http://127.0.0.1:8000.
VITE_USE_MOCK_API=false npm run dev
```

```powershell
$env:VITE_USE_MOCK_API = "true"   # or "false"
npm run dev
```

When mock mode is off (the default), Vite proxies `/v1` requests to
`http://127.0.0.1:8000` as configured in `vite.config.ts`. Start the local
service first; see [`../aiAudio_Processing/README.md`](../aiAudio_Processing/README.md).

Some dashboard flows target routes that the current backend does not implement
yet (`POST /v1/summary`, `POST /v1/privacy/delete`, `GET /v1/jobs/{job_id}`).
Those flows work in mock mode and are not functional against the live service.

## Scripts

| Command | Purpose |
| --- | --- |
| `npm run dev` | Vite dev server with HMR on `127.0.0.1:5173`. |
| `npm run build` | Type-check (`tsc -b`) and produce `dist/`. |
| `npm run lint` | ESLint over the project. |
| `npm test` | Vitest run (single pass). |
| `npm run test:watch` | Vitest in watch mode. |
| `npm run preview` | Serve the production build locally. |

## Tests

```bash
npm run lint
npm run build
npm test
```

These are the same checks run by the `web` job in
[`../.github/workflows/ci.yml`](../.github/workflows/ci.yml).

## Project layout

```text
src/
├── components/   # dashboard, settings, and ui components
├── hooks/        # state polling and playback hooks
├── services/     # API client and polling (mock vs live)
├── mocks/        # contract-valid mock data
├── types/        # shared API contracts
└── test/         # test setup
```

See the [root README](../README.md) for the full system and
[`AGENTS.md`](AGENTS.md) for frontend conventions.
