# Live Sound Radar

An accessibility-focused application that recognizes environmental sounds locally
and turns them into visual alerts with actionable next steps.

The initial goal is to detect knocking and doorbells using one microphone.
“Radar” describes sound awareness; the application does not estimate direction
or distance.

## Architecture

Microphone → C++ capture and processing → local Python classifier → web dashboard.

Raw microphone audio stays on the capture device. Optional cloud integrations
handle permitted event metadata, analytics, and spoken alerts.

## Stack

- **Capture:** C++20, miniaudio, cpp-httplib, CMake.
- **Inference/backend:** Python, YAMNet, TensorFlow, FastAPI.
- **Frontend:** React, TypeScript, Vite.
- **Cloud:** DigitalOcean, MongoDB Atlas, Snowflake, ElevenLabs.

## Planned features

- Live visual detections and local event history.
- Optional spoken alerts through ElevenLabs.
- Operational metadata storage in MongoDB Atlas.
- Event analytics and AI summaries in Snowflake.
- Explicit controls for capture, cloud sharing, and data retention.

## Getting started

The project is under development. Full application setup instructions will be
added as components are integrated.

To build the C++ component, install CMake 3.24+ and a C/C++ toolchain with C++20
support. Once `capture/src/main.cpp` exists, run from the repository root:

```bash
cmake -S capture -B build/capture -DCMAKE_BUILD_TYPE=Debug
cmake --build build/capture --config Debug --parallel
```

The first configure downloads the pinned C++ dependencies.

## Development

Read [AGENTS.md](AGENTS.md) for coding instructions and the
[architecture plan](Live-Sound-Radar-Architecture-and-Execution-Plan.md) for
component ownership, interfaces, and implementation milestones.

Keep credentials out of source control. Coordinate changes to shared contracts
with the member responsible for that interface.
