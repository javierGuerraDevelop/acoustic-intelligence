# Audio contract (Edge 1) — M1 owned

Status: v1, mirrors architecture plan section 5.2. Producer M1 (`capture/`),
consumer M2 (`local/`). Changes to headers, JSON fields, sample formats or
timing require owner review and a versioned contract update.

## 1. Chunk upload

`POST L/v1/audio/chunks`, `Content-Type: application/octet-stream`, capture
bearer token. Body is exactly **32,000 bytes**: 16,000 mono samples of signed
16-bit little-endian PCM at 16 kHz, no WAV header, no base64. One complete
one-second chunk per request. The route rejects any other size.

| Header | Value |
| --- | --- |
| `X-Schema-Version` | `1` |
| `X-Device-Id` | device UUID |
| `X-Stream-Id` | stream UUID, new on every start/pause/discontinuity |
| `X-Chunk-Seq` | integer >= 0, increases by 1 per completed chunk, even if a chunk is dropped |
| `X-Start-Sample` | `chunk_seq * 16000` within a contiguous stream |
| `X-Captured-At` | UTC RFC 3339 with milliseconds, time of the first sample |
| `X-Sample-Rate` | `16000` |
| `X-Channels` | `1` |
| `X-Encoding` | `pcm_s16le` |
| `X-Rms-Dbfs` | `[-120, 0]`, diagnostics only, silence floored at -120 |
| `X-Dropped-Frames-Total` | source-rate frames dropped since process launch |

`captured_at` is derived from stream-start wall clock plus the sample count, not
HTTP delivery time. Non-finite samples are encoded as silence. Clipping is
limited to `[-1, 1]` before the s16 conversion.

Accepted response (HTTP 202, enqueue only, not inference):

```json
{
  "schema_version": 1,
  "stream_id": "fa986755-08b7-4bb2-b324-f5d17243539c",
  "chunk_seq": 42,
  "status": "accepted",
  "queue_depth": 1
}
```

Consumer rules M2 implements: duplicate `(stream_id, chunk_seq)` returns 200
`status:"duplicate"` and must not infer twice (retain recent IDs 60 s); unknown
or closed stream, overlapping/out-of-order chunk or stopped capture returns
409; model loading 503; audio queue full 429 (queue holds at most two chunks);
body/header violations 413/415/422. Python resets its rolling window and
smoothing whenever sequence numbers skip and discards chunks whose first
sample is older than three seconds. Python performs no resampling.

## 2. Capture control heartbeat

`POST L/v1/capture/heartbeat` every 500 ms:

```json
{
  "schema_version": 1,
  "device_id": "70c4af1d-9b7c-4c28-a66c-a87489376e42",
  "stream_id": "fa986755-08b7-4bb2-b324-f5d17243539c",
  "state": "running",
  "native_rate_hz": 48000,
  "dropped_frames_total": 0,
  "error_code": null
}
```

`stream_id` is null while stopped; `state` is `stopped|starting|running|error`;
`native_rate_hz` is positive while running or null before initialization;
`error_code` is null or a short diagnostic string. Reply 200:

```json
{"schema_version": 1, "desired_capture": true, "lease_ms": 2000, "settings_revision": 4}
```

Capture starts only after a successful reply with `desired_capture: true`.
The lease is renewed by each successful heartbeat; if it expires (normally
2 seconds after the last reply) the supervisor stops the actual audio device
and clears buffered audio. A backend that is unavailable never authorizes
capture.

## 3. C++ implementation mapping

- `radar::SpscRing` — preallocated producer-drop ring, four seconds at the
  maximum supported rate (96 kHz), release/acquire index publication. The
  callback is the sole write-index owner; the processing worker is the sole
  read-index owner. Overflow drops the new frames and sets a discontinuity
  flag; the producer never moves the consumer index.
- `radar::CaptureDevice` — miniaudio device on f32 mono at the queried native
  rate. The callback copies frames and updates atomic counters only: no
  allocation, locking, logging, I/O, HTTP or device control.
- `radar::CapturePipeline` — processing worker. One persistent
  `StreamingResampler` (miniaudio linear) per stream, RMS accumulation,
  s16le encoding and one-second chunk assembly. On overflow the worker drains
  the ring, resets the converter, rotates the stream UUID and restarts
  `chunk_seq` at 0. Pause (`end_stream`) discards queued frames and the partial
  chunk and rotates the UUID on the next start.
- `radar::ChunkQueue` — mutex-protected, bounded at two completed chunks.
  Full queue drops the oldest pending chunk and counts it; the ring and the
  callback are never blocked.
- `radar::HttpSender` — one worker thread, one request in flight, keep-alive,
  200 ms connect timeout, 750 ms read/write timeout. Any error or uncertain
  response discards that chunk and advances; there is no retransmission.
  A stopped receiver therefore cannot stall capture or grow memory beyond the
  fixed ring and two-chunk queue.
- `radar::Supervisor` — heartbeat and lease state machine. It is the only
  place that starts/stops the device, retries a failed microphone at most once
  every two seconds while authorized, and reports `stopped|starting|running|error`.

Allocation, logging and blocking calls stay outside the callback. Stop order:
stop the device (waits for the callback), drain/close the pipeline, clear the
sender queue, join the sender.

## 4. Verified environment and commands

Verified on 26 September 2026 on this workstation (Windows 11 x64):

| Tool | Version |
| --- | --- |
| CMake | 4.2.3 (MinGW Makefiles generator) |
| Compiler | GCC 15.2.0 (MinGW-w64, x86_64-posix-seh) |
| miniaudio | 0.11.25 (CMake FetchContent, SHA-256 pinned) |
| cpp-httplib | 0.20.0 (CMake FetchContent, SHA-256 pinned) |
| nlohmann/json | 3.11.3 (heartbeat JSON only, SHA-256 pinned) |

```bash
cmake -S capture -B build/capture -G "MinGW Makefiles" -DCMAKE_BUILD_TYPE=Debug
cmake --build build/capture --parallel
ctest --test-dir build/capture -C Debug --output-on-failure
python tests/capture/integration_check.py --exe build/capture/bin/radar_capture.exe --scenario lifecycle
python tests/capture/integration_check.py --exe build/capture/bin/radar_capture.exe --scenario fixture
python tests/capture/integration_check.py --exe build/capture/bin/radar_capture.exe --scenario stall
```

Process entry points: `radar_capture list|smoke|run|fixture`. `fixture`
generates a 48 kHz tone through the same ring/resampler/chunker/sender path
without a microphone and is development-only (M2 must label it `fixture`).
`run --null-backend` selects miniaudio's silent null device for headless
lifecycle checks; live runs always use the default microphone.

Environment: `CAPTURE_BACKEND_URL` (or `LOCAL_HOST`/`LOCAL_PORT`),
`CAPTURE_TOKEN`, `DEVICE_ID`. The launcher passes tokens through the
environment, never command-line arguments.

## 5. Evidence from this environment

- Unit tests (CTest): ring wraparound/overflow, 48 kHz and 44.1 kHz tone
  duration and frequency preservation, sign/endian encoding, RMS floor,
  queue oldest-drop/timeout/close, UTC millisecond formatting.
- `lifecycle`: authorization starts capture, lease expiry stops it, one stream
  id, contiguous `start_sample == seq * 16000`, no gaps, heartbeat `running`
  with `native_rate_hz=48000`.
- `fixture`: 6 chunks accepted, 1.000 s `captured_at` cadence, 999.5-1000.0 Hz
  preserved after resampling to 16 kHz.
- `stall`: receiver sleeping 3 s per response; 12/12 chunks emitted and 12/12
  sends discarded, no retransmission, working set 2.2-7.7 MiB across the run.

## 6. Open items

- No capture device exists on this workstation, so live microphone framing is
  not yet observed here; `--null-backend` covers the same code path and the
  real-device check remains on a laptop with a microphone.
- The real Python receiver (`local/`) is not present yet; `tests/capture/mock_receiver.py`
  implements this contract for integration until M2 publishes the endpoint.
- Windows Smart App Control occasionally blocks or throttles a freshly built
  unsigned `radar_capture.exe`, which showed up as transient loopback connect
  timeouts on first runs of a new binary; repeated runs and signed binaries
  are unaffected. Re-run the integration check if the first post-build run
  reports connection errors.
