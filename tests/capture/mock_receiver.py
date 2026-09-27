"""Standalone mock of M2's Python ingest/control endpoints for M1 integration.

Implements the section 5.2 contract closely enough to exercise the C++ sender:

    POST /v1/audio/chunks       202 accepted / 200 duplicate / 401 / 413 / 415
    POST /v1/capture/heartbeat  200 {"desired_capture": ..., "lease_ms": ...}

Development aid only; it is not the production receiver. Options simulate slow
or failing receivers and time-boxed capture authorization. Received PCM is not
written to disk unless --dump-dir is given for fixture material.

Examples:
    python tests/capture/mock_receiver.py --port 8010 --token testtoken
    python tests/capture/mock_receiver.py --slow-ms 3000 --run-seconds 20
    python tests/capture/mock_receiver.py --desired-seconds 4
"""

from __future__ import annotations

import argparse
import json
import math
import signal
import struct
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CHUNK_BYTES = 32000
CHUNK_FRAMES = 16000
SAMPLE_RATE = 16000


class ReceiverState:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.lock = threading.Lock()
        self.started_at = time.monotonic()
        self.chunks_accepted = 0
        self.duplicates = 0
        self.rejected = 0
        self.bytes_received = 0
        self.heartbeats = 0
        self.desired_true = 0
        self.desired_false = 0
        self.heartbeat_states: dict[str, int] = {}
        self.running_streams: set[str] = set()
        self.running_rates: set[int] = set()
        self.streams: dict[str, dict] = {}
        self.violations: list[str] = []
        self.rms_values: list[float] = []
        self.last_stream_id: str | None = None
        self.last_chunk_seq: int | None = None

    def note_violation(self, message: str) -> None:
        if len(self.violations) < 50:
            self.violations.append(message)

    def stream_stats(self, stream_id: str) -> dict:
        return self.streams.setdefault(
            stream_id,
            {
                "chunks": 0,
                "seqs": set(),
                "seqs_min": -1,
                "last_seq": -1,
                "gaps": [],
                "out_of_order": 0,
                "start_sample_ok": True,
                "captured_at": [],
                "captured_epoch": [],
                "rms": [],
                "freqs": [],
            },
        )

    def desired_capture(self) -> bool:
        delay = self.args.desired_after
        duration = self.args.desired_seconds
        elapsed = time.monotonic() - self.started_at
        if delay and elapsed < delay:
            return False
        if duration and elapsed > delay + duration:
            return False
        return not self.args.no_desired

    def summary(self) -> dict:
        with self.lock:
            streams = {}
            for stream_id, stats in self.streams.items():
                captured = stats["captured_at"]
                epochs = stats["captured_epoch"]
                deltas = [b - a for a, b in zip(epochs, epochs[1:])]
                freqs = stats["freqs"]
                streams[stream_id] = {
                    "chunks": stats["chunks"],
                    "gaps": stats["gaps"][:20],
                    "out_of_order": stats["out_of_order"],
                    "start_sample_ok": stats["start_sample_ok"],
                    "captured_at_span_s": round(epochs[-1] - epochs[0], 3)
                    if len(epochs) > 1
                    else 0.0,
                    "expected_span_s": (stats["last_seq"] - stats["seqs_min"]) if stats["seqs"] else 0,
                    "captured_deltas_ok": all(abs(delta - 1.0) <= 0.02 for delta in deltas),
                    "freq_min_hz": round(min(freqs), 1) if freqs else None,
                    "freq_max_hz": round(max(freqs), 1) if freqs else None,
                    "first_captured_at": captured[0] if captured else None,
                    "last_captured_at": captured[-1] if captured else None,
                }
            return {
                "chunks_accepted": self.chunks_accepted,
                "duplicates": self.duplicates,
                "rejected": self.rejected,
                "bytes_received": self.bytes_received,
                "heartbeats": self.heartbeats,
                "desired_true": self.desired_true,
                "desired_false": self.desired_false,
                "heartbeat_states": dict(self.heartbeat_states),
                "running_streams": sorted(self.running_streams),
                "running_rates": sorted(self.running_rates),
                "streams": streams,
                "violations": self.violations,
                "rms_min": min(self.rms_values) if self.rms_values else None,
                "rms_max": max(self.rms_values) if self.rms_values else None,
            }


class Handler(BaseHTTPRequestHandler):
    state: ReceiverState
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib sig
        if self.state.args.verbose:
            sys.stderr.write("mock_receiver: " + (format % args) + "\n")

    def setup(self) -> None:
        super().setup()
        if self.state.args.verbose:
            sys.stderr.write(f"mock_receiver: connection opened {self.client_address}\n")

    def finish(self) -> None:
        if self.state.args.verbose:
            sys.stderr.write(f"mock_receiver: connection closed {self.client_address}\n")
        super().finish()

    def _authorized(self) -> bool:
        expected = self.state.args.token
        if not expected:
            return True
        return self.headers.get("Authorization") == f"Bearer {expected}"

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - stdlib name
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_000_000:
            self._send_json(413, {"schema_version": 1, "error": {"code": "TOO_LARGE"}})
            return
        body = self.rfile.read(length)
        if self.path == "/v1/capture/heartbeat":
            self._handle_heartbeat(body)
        elif self.path == "/v1/audio/chunks":
            self._handle_chunk(body)
        else:
            self._send_json(404, {"schema_version": 1, "error": {"code": "NOT_FOUND"}})

    def _handle_heartbeat(self, body: bytes) -> None:
        if not self._authorized():
            self._send_json(401, {"schema_version": 1, "error": {"code": "UNAUTHORIZED"}})
            return
        try:
            request = json.loads(body)
        except json.JSONDecodeError:
            self._send_json(400, {"schema_version": 1, "error": {"code": "BAD_JSON"}})
            return
        desired = self.state.desired_capture()
        heartbeat_state = str(request.get("state", "unknown"))
        with self.state.lock:
            self.state.heartbeats += 1
            if desired:
                self.state.desired_true += 1
            else:
                self.state.desired_false += 1
            self.state.heartbeat_states[heartbeat_state] = (
                self.state.heartbeat_states.get(heartbeat_state, 0) + 1
            )
            stream_id = request.get("stream_id")
            native_rate = request.get("native_rate_hz")
            if heartbeat_state == "running" and stream_id:
                self.state.running_streams.add(str(stream_id))
            if heartbeat_state == "running" and native_rate:
                self.state.running_rates.add(int(native_rate))
        if self.state.args.verbose:
            sys.stderr.write(
                f"mock_receiver: heartbeat state={request.get('state')} "
                f"stream={request.get('stream_id')} rate={request.get('native_rate_hz')} "
                f"-> desired={desired}\n"
            )
        self._send_json(
            200,
            {
                "schema_version": 1,
                "desired_capture": desired,
                "lease_ms": self.state.args.lease_ms,
                "settings_revision": 1,
            },
        )

    def _handle_chunk(self, body: bytes) -> None:
        state = self.state
        if not self._authorized():
            with state.lock:
                state.rejected += 1
            self._send_json(401, {"schema_version": 1, "error": {"code": "UNAUTHORIZED"}})
            return
        content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip()
        if content_type != "application/octet-stream":
            with state.lock:
                state.rejected += 1
            self._send_json(415, {"schema_version": 1, "error": {"code": "BAD_CONTENT_TYPE"}})
            return
        if len(body) != CHUNK_BYTES:
            with state.lock:
                state.rejected += 1
                state.note_violation(f"body_bytes={len(body)}")
            self._send_json(413, {"schema_version": 1, "error": {"code": "BAD_LENGTH"}})
            return

        try:
            stream_id = self.headers["X-Stream-Id"]
            chunk_seq = int(self.headers["X-Chunk-Seq"])
            start_sample = int(self.headers["X-Start-Sample"])
            captured_at = self.headers["X-Captured-At"]
            rms = float(self.headers["X-Rms-Dbfs"])
        except (KeyError, ValueError) as exc:
            with state.lock:
                state.rejected += 1
                state.note_violation(f"header_error={exc}")
            self._send_json(422, {"schema_version": 1, "error": {"code": "BAD_HEADER"}})
            return

        if (
            self.headers.get("X-Schema-Version") != "1"
            or self.headers.get("X-Sample-Rate") != str(SAMPLE_RATE)
            or self.headers.get("X-Channels") != "1"
            or self.headers.get("X-Encoding") != "pcm_s16le"
        ):
            with state.lock:
                state.rejected += 1
                state.note_violation("fixed_header_mismatch")
            self._send_json(422, {"schema_version": 1, "error": {"code": "BAD_HEADER"}})
            return

        samples = struct.unpack(f"<{CHUNK_FRAMES}h", body)
        nonzero = sum(1 for sample in samples if sample)
        crossings = sum(
            1
            for a, b in zip(samples, samples[1:])
            if (a < 0 <= b) or (a > 0 >= b)
        )
        tone_hz = crossings / 2.0  # one chunk spans exactly one second
        captured_epoch = datetime.fromisoformat(captured_at.replace("Z", "+00:00")).timestamp()
        with state.lock:
            stats = state.stream_stats(stream_id)
            if chunk_seq in stats["seqs"]:
                state.duplicates += 1
                duplicate = True
            else:
                duplicate = False
                stats["seqs"].add(chunk_seq)
                stats["chunks"] += 1
                state.chunks_accepted += 1
                state.bytes_received += len(body)
                state.last_stream_id = stream_id
                state.last_chunk_seq = chunk_seq
                if stats["last_seq"] >= 0 and chunk_seq != stats["last_seq"] + 1:
                    if chunk_seq < stats["last_seq"]:
                        stats["out_of_order"] += 1
                    else:
                        stats["gaps"].append(f"{stats['last_seq']}->{chunk_seq}")
                stats["last_seq"] = max(stats["last_seq"], chunk_seq)
                if stats["seqs_min"] < 0 or chunk_seq < stats["seqs_min"]:
                    stats["seqs_min"] = chunk_seq
                if start_sample != chunk_seq * CHUNK_FRAMES:
                    stats["start_sample_ok"] = False
                stats["captured_at"].append(captured_at)
                stats["captured_epoch"].append(captured_epoch)
                stats["rms"].append(rms)
                stats["freqs"].append(tone_hz)
                state.rms_values.append(rms)
                if state.args.verbose:
                    sys.stderr.write(
                        f"mock_receiver: chunk stream={stream_id} seq={chunk_seq} "
                        f"rms={rms:.1f} captured_at={captured_at} nonzero={nonzero}\n"
                    )
                if state.args.dump_dir:
                    path = f"{state.args.dump_dir}/chunk_{stream_id}_{chunk_seq:05d}.raw"
                    with open(path, "wb") as handle:
                        handle.write(body)

        if state.args.status and (state.chunks_accepted % state.args.fail_every == 0):
            with state.lock:
                state.rejected += 1
            self._send_json(state.args.status, {"schema_version": 1, "error": {"code": "SIMULATED"}})
            return

        if state.args.slow_ms:
            time.sleep(state.args.slow_ms / 1000.0)

        if duplicate:
            self._send_json(
                200,
                {
                    "schema_version": 1,
                    "stream_id": stream_id,
                    "chunk_seq": chunk_seq,
                    "status": "duplicate",
                    "queue_depth": 0,
                },
            )
            return
        self._send_json(
            202,
            {
                "schema_version": 1,
                "stream_id": stream_id,
                "chunk_seq": chunk_seq,
                "status": "accepted",
                "queue_depth": 0,
            },
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--token", default="", help="expected bearer token; empty disables auth")
    parser.add_argument("--desired-seconds", type=int, default=0, help="authorize capture only this long")
    parser.add_argument("--desired-after", type=int, default=0, help="delay authorization this long")
    parser.add_argument("--no-desired", action="store_true", help="never authorize capture")
    parser.add_argument("--lease-ms", type=int, default=2000)
    parser.add_argument("--slow-ms", type=int, default=0, help="delay each chunk response")
    parser.add_argument("--status", type=int, default=0, help="return this status instead of 202")
    parser.add_argument("--fail-every", type=int, default=1)
    parser.add_argument("--run-seconds", type=int, default=0, help="exit after this long")
    parser.add_argument("--dump-dir", default="", help="write raw fixture chunks (fixture mode only)")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    state = ReceiverState(args)
    handler = type("BoundHandler", (Handler,), {"state": state})
    server = ThreadingHTTPServer((args.host, args.port), handler)
    server.daemon_threads = True

    stopping = threading.Event()

    def request_stop(*_unused) -> None:
        stopping.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    if args.run_seconds:
        threading.Timer(args.run_seconds, server.shutdown).start()

    print(f"mock_receiver: listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    print("mock_receiver: summary " + json.dumps(state.summary(), sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
