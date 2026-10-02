# Capture (M1)

C++20 capture process for Live Sound Radar: one microphone in, one-second
16 kHz mono s16le chunks over loopback HTTP to the local Python service. The
wire contract and implementation rules are in `docs/audio-contract.md`.

## Architecture

```
microphone -> CaptureDevice callback -> SPSC ring -> processing worker
    (resample 16 kHz, RMS, s16le, 1 s chunks) -> bounded sender queue
    -> HttpSender thread -> POST 127.0.0.1:8000/v1/audio/chunks
supervisor thread -> POST /v1/capture/heartbeat every 500 ms -> start/stop device
```

The audio callback only copies frames and updates atomics. Allocation, locks,
logging, HTTP and device control stay on worker/supervisor threads.

## Prerequisites

- CMake 3.24+ (verified 4.2.3)
- C++20 compiler (verified GCC 15.2.0 MinGW-w64; MSVC is intended but was not
  available on this workstation)
- A microphone for live capture; `--null-backend` and `fixture` run headless
- Python 3.11–3.13 only for the mock receiver and integration driver

CMake downloads these pinned dependencies on first configure:

| Dependency | Version | SHA-256 |
| --- | --- | --- |
| miniaudio | 0.11.25 | `b900edcffe979816e2560a0580b9b1216d674b4f17fbadeca8f777a7f8ab0274` |
| cpp-httplib | v0.20.0 | `18064587e0cc6a0d5d56d619f4cbbcaba47aa5d84d86013abbd45d95c6653866` |
| nlohmann/json | v3.11.3 | `0d8ef5af7f9794e3263480193c491549b2ba6cc74bb018906202ada498a79406` |

## Build and test

From the repository root. Linux/macOS (default generator):

```bash
cmake -S capture -B build/capture -DCMAKE_BUILD_TYPE=Debug
cmake --build build/capture --parallel
ctest --test-dir build/capture --output-on-failure
```

Windows (MinGW Makefiles, the originally verified toolchain):

```powershell
cmake -S capture -B build/capture -G "MinGW Makefiles" -DCMAKE_BUILD_TYPE=Debug
cmake --build build/capture --parallel
ctest --test-dir build/capture -C Debug --output-on-failure
```

Release build in a separate directory (add `-G "MinGW Makefiles"` on Windows):

```bash
cmake -S capture -B build/capture-release -DCMAKE_BUILD_TYPE=Release
cmake --build build/capture-release --parallel
```

## Run

The binary is `build/capture/bin/radar_capture` on Linux/macOS and
`build\capture\bin\radar_capture.exe` on Windows.

```bash
build/capture/bin/radar_capture list
build/capture/bin/radar_capture smoke --seconds 3          # live mic RMS diagnostics
build/capture/bin/radar_capture smoke --null-backend       # headless callback timing
build/capture/bin/radar_capture run                        # supervised capture + sender
build/capture/bin/radar_capture fixture --seconds 6        # synthetic tone through the pipeline
```

```powershell
.\build\capture\bin\radar_capture.exe list
.\build\capture\bin\radar_capture.exe smoke --seconds 3
.\build\capture\bin\radar_capture.exe smoke --null-backend
.\build\capture\bin\radar_capture.exe run
.\build\capture\bin\radar_capture.exe fixture --seconds 6
```

`run` reads `CAPTURE_BACKEND_URL` (or `LOCAL_HOST`/`LOCAL_PORT`),
`CAPTURE_TOKEN` and `DEVICE_ID` from the environment; `--backend`,
`--token` and `--device-id` override them. Capture stays off until a
heartbeat replies `desired_capture: true`, and stops within two seconds if the
lease is not renewed.

## Mock receiver and integration checks

`tests/capture/integration_check.py` starts the receiver itself and drives the
three acceptance scenarios (the standalone receiver command below is only for
manual debugging):

```bash
python3 tests/capture/mock_receiver.py --port 8010 --token testtoken --verbose
python3 tests/capture/integration_check.py --exe build/capture/bin/radar_capture --scenario lifecycle
python3 tests/capture/integration_check.py --exe build/capture/bin/radar_capture --scenario fixture
python3 tests/capture/integration_check.py --exe build/capture/bin/radar_capture --scenario stall
```

```powershell
python tests\capture\mock_receiver.py --port 8010 --token testtoken --verbose
python tests\capture\integration_check.py --exe build\capture\bin\radar_capture.exe --scenario lifecycle
python tests\capture\integration_check.py --exe build\capture\bin\radar_capture.exe --scenario fixture
python tests\capture\integration_check.py --exe build\capture\bin\radar_capture.exe --scenario stall
```

## Troubleshooting

- No capture devices: `radar_capture list` prints `capture devices: 0`. Use a
  USB microphone or run the null-backend/fixture modes; report live capture as
  unverified until a microphone exists.
- Windows Smart App Control may block or throttle a freshly built unsigned
  executable; the first run after a rebuild can show transient loopback
  connect timeouts. Re-run, or sign the binary for the demo machine.
- `CAPTURE_TOKEN` is intentionally not accepted on the command line by the
  launcher; pass it through the environment.
