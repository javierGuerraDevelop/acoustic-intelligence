# AGENTS.md (capture)

C++ instructions for Live Sound Radar's capture component.
Known project details are filled in; replace bracketed fields when established.
For rules shared across the whole repo (secrets, branching, parallel agents,
handoff), see the root AGENTS.md — this file covers capture/C++ specifics only.

## Stack
- C++20; CMake 3.24+; miniaudio and cpp-httplib, pinned in CMake.
- Compiler/toolchain: [compiler and version used by the team].
- Format: repository .clang-format; tests: [chosen framework], run through CTest.
- C++ captures/resamples audio; Python performs local inference.

## Project structure
- capture/src/, capture/include/ — implementation and headers.
- capture/CMakeLists.txt — capture build; explicitly list new .cpp files.
- tests/capture/ — capture tests; register through capture/tests/CMakeLists.txt.
- contracts/, docs/audio-contract.md — shared interfaces and audio framing.
- build/ — ignored build output and downloaded dependencies.

## Setup and commands
Run from the repository root. Create capture/src/main.cpp before configuring.
The first configure downloads dependencies. Miniaudio's implementation is already
compiled by CMake: include its header without MINIAUDIO_IMPLEMENTATION.

```
cmake --version
cmake -S capture -B build/capture -DCMAKE_BUILD_TYPE=Debug
cmake --build build/capture --config Debug --parallel
ctest --test-dir build/capture -C Debug --output-on-failure
```

For an optimized build, use a separate directory:

```
cmake -S capture -B build/capture-release -DCMAKE_BUILD_TYPE=Release
cmake --build build/capture-release --config Release --parallel
```

Prefer established CMake presets if the team later adds them.
Zero discovered tests means tests are missing, not that verification passed.

## C++ style and ownership
- Follow .clang-format and nearby naming; format only touched code.
- Prefer simple functions, value ownership, RAII, and std::unique_ptr.
- Use std::shared_ptr only when shared lifetime is actually required.
- Treat pointers, references, spans, and string views as borrowed lifetimes.
  Queued work must own its data or hold a valid lease on its buffer.
- Validate lengths, integer conversions, alignment, and byte order at boundaries.
- Handle device/network errors explicitly; exceptions must not escape callbacks
  or worker entry points. Cleanup must handle partially initialized resources.
- Keep code C++20-compatible; use target-scoped CMake settings and pinned dependencies.
- Fix new compiler warnings; avoid broad suppressions or unrelated abstractions.

## Audio and concurrency

| Context | Required behavior |
|---|---|
| Audio callback | Copy to preallocated storage; update counters; return promptly. |
| Processing worker | Resample, compute RMS, encode PCM, preserve conversion state. |
| Sender worker | Perform bounded HTTP requests and handle backpressure. |
| Supervisor | Start/stop the device, handle leases, coordinate shutdown. |

- Keep allocation/deallocation, blocking locks, logging, I/O, HTTP, and device
  start/stop outside the callback.
- In an SPSC ring, each side owns its index; producer overflow drops new data
  and reports the gap rather than changing the consumer's index.
- Bound every queue and implement the contract's drop/reset policy.
- Document atomic publication ordering; volatile does not synchronize threads.
- Use monotonic time for deadlines and UTC for external timestamps.
- Stop capture, let callbacks finish, cancel/wake and join workers, then destroy
  their resources. Avoid detached threads and joining while holding needed locks.
- Wire format: 16 kHz mono s16le, one-second chunks, 32,000 bytes, no WAV header.
- Keep raw microphone audio in bounded local memory; no recording or cloud upload.

## Testing
- Test framing/resampling, ring wraparound/overflow, gaps, malformed input,
  slow/disconnected receivers, and stop/restart/shutdown as relevant to the change.
- Add regression tests for nontrivial bugs; use the smallest useful test harness.
- Use ASan/UBSan where supported; use TSan separately for concurrency checks.
- Measure before claiming latency or allocation improvements. Mock tests do not
  establish microphone behavior or live service access.
