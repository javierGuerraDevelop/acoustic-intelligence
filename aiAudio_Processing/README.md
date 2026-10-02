# Live Sound Radar — local inference service

FastAPI + YAMNet service for Live Sound Radar. It receives 16 kHz mono PCM chunks
from the C++ capture process (or a WAV fixture upload), classifies them locally
with YAMNet, persists detection metadata in SQLite, and exposes the REST contract
consumed by the React dashboard. Raw microphone audio is never written to disk or
sent to a cloud service.

See the [root README](../README.md) for the full three-part system, the capture
component, and privacy design. The wire format is documented in
[`../docs/audio-contract.md`](../docs/audio-contract.md).

## Requirements

- Python **3.11–3.13** (3.13 verified). TensorFlow 2.21 does not publish wheels
  for Python 3.14.
- No cloud credentials are required for local detection.
- Optional: ElevenLabs credentials for spoken alerts.

## Setup

Run these commands from `aiAudio_Processing`.

### POSIX

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-local.lock
```

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-local.lock
```

## Download the model (required)

The API never downloads a model at runtime, and the model is not committed to
the repository. Download it once:

```bash
.venv/bin/python scripts/download_model.py
```

```powershell
.\.venv\Scripts\python.exe scripts\download_model.py
```

The default output is `models/yamnet`. The script **refuses to overwrite an
existing output directory** (it exits with an error), so it is safe to re-run
but unnecessary once the model is present. Use `--output <directory>` to place
the model elsewhere, then point `MODEL_DIR` at that directory.

## Configuration

Set variables in the shell that starts Uvicorn. `.env.example` documents the
same names; it is not loaded automatically.

| Variable | Default | Purpose |
| --- | --- | --- |
| `MODEL_DIR` | *(required)* | YAMNet `saved_model.pb` directory. |
| `LOCAL_DB_PATH` | `data/events.sqlite3` | SQLite event store path. |
| `RETENTION_DAYS` | `1` | Local retention window; `1` or `7`. |
| `CAPTURE_TOKEN` | *(empty)* | When set, capture endpoints require `Authorization: Bearer <token>`; the capture process must use the same value. |
| `ELEVENLABS_API_KEY` | *(empty)* | Enables speech synthesis with `ELEVENLABS_VOICE_ID`. |
| `ELEVENLABS_VOICE_ID` | *(empty)* | ElevenLabs voice used for alerts. |
| `ELEVENLABS_MODEL_ID` | `eleven_multilingual_v2` | ElevenLabs model id. |

`models/` and `data/` are gitignored download/runtime directories.

## Run

From `aiAudio_Processing`:

```bash
MODEL_DIR="$PWD/models/yamnet" .venv/bin/python -m uvicorn api:app --host 127.0.0.1 --port 8000
```

```powershell
$env:MODEL_DIR = (Resolve-Path ".\models\yamnet").Path
.\.venv\Scripts\python.exe -m uvicorn api:app --host 127.0.0.1 --port 8000
```

Health endpoints:

```text
GET /health/live   -> {"status":"alive"}
GET /health/ready  -> {"status":"ready","model":"YAMNet"}
```

`/health/ready` returns `503` until YAMNet finishes loading. In production the
Vite build in `../web/dist` is served at `/` when it exists.

## API routes

| Method | Route | Notes |
| --- | --- | --- |
| `GET` | `/health/live` | Liveness; no model dependency. |
| `GET` | `/health/ready`, `/health` | Readiness; `503` until the model is loaded. |
| `POST` | `/classify-file` | Classify an uploaded WAV fixture; `204` when no detection. |
| `POST` | `/v1/capture/heartbeat` | Capture lease and settings revision; token-protected when configured. |
| `POST` | `/v1/audio/chunks` | 32,000-byte s16le PCM chunks; token-protected when configured. |
| `GET` | `/v1/state` | System state plus cursor-based change feed. |
| `GET` | `/v1/events` | Live event history with paging and acknowledgement state. |
| `POST` | `/v1/events/{event_id}/ack` | Acknowledge an event. |
| `GET` | `/v1/settings` | Read settings. |
| `PATCH` | `/v1/settings` | Update settings with optimistic revision checks. |
| `POST` | `/v1/speech` | Generate MP3 speech for an eligible recent event. |
| `POST` | `/v1/playback` | Register speech playback start/end for detection suppression. |
| `POST` | `/v1/summary` | Start an AI activity summary job (`202`); requires analytics consent. |
| `POST` | `/v1/privacy/delete` | Start a history-deletion job (`202`); always clears local history. |
| `GET` | `/v1/jobs/{job_id}` | Poll a background job (`pending`/`running`/`complete`/`failed`). |
| `GET` | `/events` | Legacy event list retained for compatibility. |

### Snowflake summaries and remote deletion

`POST /v1/summary` and `POST /v1/privacy/delete` return a background `Job`:
`{schema_version, job_id, kind, state, updated_at, result, error}`. Jobs are
process-local (a restart clears them, matching the `/v1/state` reset behavior)
and publish `job.changed` on the change feed.

Summary generation:

- Requires `analytics_enabled` in settings; otherwise the route returns `403`.
- Valid `lookback_minutes` are 5–60. Only one summary runs at a time and at most
  one starts per minute; duplicates by `request_id` return the same job.
- Uses the Snowflake adapter in [`../cloud/analytics`](../cloud/analytics/README.md)
  when `SNOWFLAKE_*` variables are configured. Install its optional dependencies
  into the service environment first:

  ```bash
  .venv/bin/python -m pip install -r ../cloud/analytics/requirements-analytics.lock
  ```

  Without credentials the job fails with a retryable `DEPENDENCY_UNAVAILABLE`
  error rather than fabricating a summary.

History deletion:

- Clears local SQLite history, disables cloud-storage/analytics/speech
  permissions, advances the local policy epoch, and clears pending change-feed
  entries before publishing `history.cleared`.
- Calls the Snowflake adapter's device deletion when it is configured; a remote
  failure marks the job failed with a `snowflake: "pending"` partial result
  while the local deletion stays complete.
- This build has no MongoDB Atlas integration, so no metadata was ever uploaded
  there; the Atlas leg reports `complete` by construction.

The local detection pipeline does not depend on either integration.

## Tests

The suite uses fake classifiers and does not need YAMNet or `MODEL_DIR`:

```bash
.venv/bin/python -m pytest ../tests -q
```

```powershell
.\.venv\Scripts\python.exe -m pytest ..\tests -q
```

## Module map

- `api.py` — FastAPI app, routes, error envelope, lifespan/model loading.
- `ingest.py` — heartbeat registry, chunk parsing/validation, bounded queue.
- `pipeline.py` — windowing and detection-to-event flow.
- `classifier.py` — YAMNet loading and scoring.
- `detector.py` — thresholds, smoothing, cooldown rules.
- `events.py` — canonical event construction/formatting.
- `storage.py` — SQLite event and settings stores, device identity/policy epoch.
- `changes.py` — cursor-based change buffer for `/v1/state`.
- `jobs.py` — in-process job registry for summaries and history deletion.
- `analytics.py` — optional Snowflake adapter wiring and sanitized errors.
- `speech.py` — ElevenLabs speech service.
- `playback.py` — playback lease/detection suppression.
- `scripts/download_model.py` — explicit one-time YAMNet download.
