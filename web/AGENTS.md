# AGENTS.md — Web Frontend

Instructions for agents working inside `web/`. The repository root `AGENTS.md` also applies. This file adds frontend-specific ownership, architecture, implementation, and accessibility rules.

## Ownership

Member 3 owns the web frontend and product experience.

Primary frontend responsibilities:

- React dashboard and overall UI behavior.
- Live listening and system status presentation.
- Visual presentation of detected `knock` and `doorbell` events.
- Local event history.
- Start/stop listening controls.
- Event acknowledgement.
- Privacy, cloud-storage, analytics, speech, and retention controls.
- Snowflake-generated summary presentation supplied by the backend.
- ElevenLabs speech controls and browser audio playback.
- Error, disconnected, degraded, pending, and offline states.
- Keyboard accessibility and accessible visual alerts.
- Frontend tests and demo/privacy copy assigned to M3.

Do not modify another member's capture, inference, Atlas, Snowflake, or shared-contract implementation without coordination with its owner.

## Stack

Use:

- React
- TypeScript
- Vite
- shadcn/ui
- Tailwind CSS
- Radix UI primitives through shadcn/ui
- Native `fetch`
- Native browser audio APIs

Do not introduce another frontend framework, state-management library, networking library, component system, or major dependency unless there is a demonstrated need.

## Development Architecture

During development:

- Vite runs at `http://127.0.0.1:5173`.
- The local FastAPI service runs at `http://127.0.0.1:8000`.
- Vite proxies `/v1` requests to the local FastAPI service.

The frontend must call backend routes using same-origin paths such as:

`/v1/state`

Do not hard-code cloud service URLs into React components.

Do not call DigitalOcean, MongoDB Atlas, Snowflake, or ElevenLabs directly from the browser.

No provider credentials, API keys, backend tokens, or secrets may enter frontend code.

For the final demo, the Vite production build is served by FastAPI at `http://127.0.0.1:8000/`.

## Shared Contracts

The architecture specification and M2-owned canonical contracts are the source of truth.

Do not invent, rename, or silently change API fields or endpoints.

TypeScript interfaces must mirror the canonical backend schemas.

Important event terminology:

- `label` is `knock | doorbell`.
- `severity` is `info | attention`.
- `model_score` is a model output aggregate from 0 to 1.
- Display it as **Model score**.
- Never describe `model_score` as accuracy, certainty, probability, or calibrated confidence.
- Detection language must remain cautious, such as **Possible knocking** or **Possible doorbell**.

## Polling

The MVP uses HTTP polling.

Poll:

`GET /v1/state`

approximately every 250 ms while the page is active.

There must be only one state request in flight at a time.

Pause polling while the browser tab is hidden and immediately refresh when it becomes visible again.

Follow the contract's cursor, `instance_id`, and `reset_required` behavior.

Do not introduce WebSockets or Server-Sent Events unless the architecture contract is explicitly changed by the team.

If the frontend has not received a successful state response for two seconds, it must stop presenting the system as healthy and show a disconnected state.

## Mock Development

Frontend development must continue even when M2's backend is unavailable.

Use contract-valid mock data and fixtures.

Suggested structure:

```text
src/
├── components/
│   └── ui/
├── pages/
├── services/
├── types/
├── mocks/
└── lib/
```

Mocks must conform to the real contracts so replacing mock data with the backend does not require redesigning the UI.

Clearly distinguish mocked behavior from live integration when reporting verification.

## Product Priorities

Build in this order unless an integration requirement changes the priority:

1. Dashboard shell and layout.
2. Contract-valid fixture data.
3. Listening, model, cloud, and connection status.
4. Prominent visual detection alert.
5. Recent event history.
6. Start/stop listening control.
7. Event acknowledgement.
8. Real polling and backend control wiring.
9. Privacy and data controls.
10. ElevenLabs **Speak alert** action and browser playback.
11. Snowflake summary presentation.
12. Error states, accessibility verification, and demo polish.

Prefer a small, reliable vertical slice over additional screens or visual complexity.

## Detection UI

The product is an acoustic-awareness dashboard.

“Radar” is a product metaphor only.

Do not display or imply:

- Direction of a sound.
- Distance to a sound.
- Room or physical location.
- Fabricated sound positions.
- Confirmed real-world causes.

The central listening indicator may visually communicate that monitoring is active, but it must not imply spatial localization.

Visual alerts are the primary notification mechanism.

Speech is supplementary.

## Accessibility

The dashboard must remain useful without hearing.

Do not rely on:

- Sound alone.
- Color alone.
- Automatic speech as the only alert.

Use:

- Semantic HTML.
- Keyboard-accessible controls.
- Visible focus states.
- Text labels.
- Sufficient contrast.
- Clear status text.
- Icons only when accompanied by an accessible name or supporting text where necessary.

`info` and `attention` may influence visual priority, but severity must remain understandable without color.

Acknowledgement must be keyboard accessible.

## Speech / ElevenLabs

Baseline speech behavior is explicitly user initiated.

Provide a **Speak alert** action for an eligible recent event.

The frontend calls the local backend; it never calls ElevenLabs directly.

The backend returns `audio/mpeg`.

The frontend:

1. Requests speech.
2. Obtains the response as a `Blob`.
3. Creates an object URL.
4. Registers playback according to the playback contract.
5. Plays using browser audio.
6. Revokes the object URL when finished.

While speech playback temporarily suppresses detection, visibly show:

**Speech playing; detection temporarily paused.**

If speech generation or playback fails, preserve the visual alert and show a normal failure state.

Automatic speech playback is a stretch feature and must not replace explicit **Speak alert** behavior in the MVP.

## Privacy

The interface must accurately communicate that detection and raw audio processing occur locally.

Raw microphone audio must never be represented as being uploaded to cloud services.

Cloud storage, analytics, and speech permissions are separate controls according to the shared settings contract.

Do not imply that pseudonymous metadata is anonymous.

Privacy controls must clearly expose pending, completed, failed, offline, and deletion states where required by the contract.

## Scope

Do not add baseline features for:

- Signup or authentication UI.
- Multi-device fleet management.
- Mobile applications.
- Custom model training.
- Remote microphone access.
- Sound direction or distance estimation.
- Room localization.
- Emergency-response automation.
- Extra detection classes.
- Elaborate analytics.
- Complex animation.
- Automatic speech.
- WebSockets or SSE.

These are outside the current MVP unless the team explicitly changes scope.

## Implementation Workflow

Before substantial frontend changes:

1. Inspect the existing code.
2. Inspect relevant shared contracts.
3. Check Git status.
4. Implement a small runnable increment.
5. Run the frontend.
6. Run applicable checks/tests.
7. Inspect the diff.
8. Report what was actually verified.

Preserve teammate changes and shared interfaces.

Do not commit secrets, `.env` files, generated build output, or temporary recordings.