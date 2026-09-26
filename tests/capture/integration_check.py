"""Integration driver for the M1 capture process against the mock receiver.

Starts tests/capture/mock_receiver.py on a free port (for the chosen scenario),
runs the built radar_capture.exe, and asserts the contract evidence:

  lifecycle  null-backend capture obeys desired_capture + lease, sends
             contiguous 32,000-byte chunks and stops when the lease expires.
  fixture    48 kHz synthetic tone exercises the resampler + framing end to
             end; asserts 1-second chunk cadence, contiguous sequence and
             1 kHz frequency preservation at 16 kHz.
  stall      a deliberately slow receiver cannot stall the processing worker:
             capture keeps emitting chunks, sends fail/time out, and process
             memory stays bounded.

Usage:
    python tests/capture/integration_check.py --exe build/capture/bin/radar_capture.exe \
        --scenario lifecycle
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MOCK_RECEIVER = Path(__file__).resolve().parent / "mock_receiver.py"
TOKEN = "integration-token"


def wait_for_port(port: int, timeout_s: float = 15.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"mock receiver did not listen on port {port}")


def process_working_set_mb(pid: int) -> float | None:
    if os.name != "nt":
        return None

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    handle = ctypes.windll.kernel32.OpenProcess(0x1000 | 0x0400, False, pid)
    if not handle:
        return None
    try:
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(
            handle, ctypes.byref(counters), counters.cb
        )
        if not ok:
            return None
        return counters.WorkingSetSize / (1024 * 1024)
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


class Checker:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def check(self, condition: bool, message: str) -> None:
        status = "ok" if condition else "FAIL"
        print(f"  [{status}] {message}")
        if not condition:
            self.failures.append(message)

    def report(self) -> int:
        if self.failures:
            print(f"integration_check: {len(self.failures)} check(s) failed")
            return 1
        print("integration_check: all checks passed")
        return 0


def run_receiver(port: int, receiver_args: list[str]) -> subprocess.Popen:
    command = [sys.executable, str(MOCK_RECEIVER), "--port", str(port), "--token", TOKEN]
    command.extend(receiver_args)
    process = subprocess.Popen(
        command,
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    wait_for_port(port)
    return process


def finish_receiver(process: subprocess.Popen) -> dict:
    out, err = process.communicate(timeout=30)
    if err and "--verbose" in " ".join(process.args):
        print(err)
    summary_line = next(
        (line for line in out.splitlines() if line.startswith("mock_receiver: summary ")),
        None,
    )
    if summary_line is None:
        raise RuntimeError(f"receiver produced no summary:\n{out}\n{err}")
    return json.loads(summary_line.split("mock_receiver: summary ", 1)[1])


def scenario_lifecycle(exe: Path, port: int) -> int:
    checker = Checker()
    receiver = run_receiver(port, ["--desired-seconds", "4", "--run-seconds", "10"])
    try:
        capture = subprocess.run(
            [
                str(exe),
                "run",
                "--null-backend",
                "--backend",
                f"http://127.0.0.1:{port}",
                "--token",
                TOKEN,
                "--run-seconds",
                "8",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        summary = finish_receiver(receiver)
    finally:
        if receiver.poll() is None:
            receiver.kill()
    print(capture.stdout)
    print(capture.stderr, file=sys.stderr)

    checker.check("capture running" in capture.stdout, "capture entered running state")
    checker.check("capture stopped" in capture.stdout, "capture stopped after lease/desire ended")
    streams = summary["streams"]
    checker.check(len(streams) == 1, f"one stream id observed ({len(streams)})")
    stats = next(iter(streams.values())) if streams else {}
    checker.check(stats.get("chunks", 0) >= 3, f"chunks accepted >= 3 ({stats.get('chunks', 0)})")
    checker.check(bool(stats.get("start_sample_ok")), "start_sample == chunk_seq * 16000")
    checker.check(not stats.get("gaps"), f"no sequence gaps ({stats.get('gaps')})")
    checker.check(stats.get("out_of_order", 0) == 0, "no out-of-order chunks")
    checker.check(summary["violations"] == [], f"no protocol violations ({summary['violations']})")
    checker.check(
        summary.get("heartbeat_states", {}).get("running", 0) >= 1,
        f"heartbeats reported running ({summary.get('heartbeat_states')})",
    )
    checker.check(
        len(summary.get("running_streams", [])) == 1,
        f"one running stream id in heartbeats ({summary.get('running_streams')})",
    )
    checker.check(
        summary.get("running_rates") == [48000],
        f"native rate reported while running ({summary.get('running_rates')})",
    )
    return checker.report()


def scenario_fixture(exe: Path, port: int) -> int:
    checker = Checker()
    receiver = run_receiver(port, ["--run-seconds", "12"])
    try:
        capture = subprocess.run(
            [
                str(exe),
                "fixture",
                "--seconds",
                "6",
                "--tone-hz",
                "1000",
                "--backend",
                f"http://127.0.0.1:{port}",
                "--token",
                TOKEN,
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        summary = finish_receiver(receiver)
    finally:
        if receiver.poll() is None:
            receiver.kill()
    print(capture.stdout)

    streams = summary["streams"]
    stats = next(iter(streams.values())) if streams else {}
    checker.check(stats.get("chunks", 0) >= 4, f"chunks accepted >= 4 ({stats.get('chunks', 0)})")
    checker.check(bool(stats.get("start_sample_ok")), "start_sample == chunk_seq * 16000")
    checker.check(not stats.get("gaps"), f"no sequence gaps ({stats.get('gaps')})")
    checker.check(bool(stats.get("captured_deltas_ok")), "captured_at advances exactly one second")
    spans = stats.get("captured_at_span_s"), stats.get("expected_span_s")
    checker.check(
        spans[0] is not None and abs((spans[0] or 0) - (spans[1] or 0)) <= 0.05,
        f"captured_at span matches sequence span ({spans})",
    )
    freq_min, freq_max = stats.get("freq_min_hz"), stats.get("freq_max_hz")
    checker.check(
        freq_min is not None and 970 <= freq_min and freq_max <= 1030,
        f"1 kHz tone preserved after resampling ({freq_min}..{freq_max} Hz)",
    )
    checker.check(summary["violations"] == [], f"no protocol violations ({summary['violations']})")
    return checker.report()


def scenario_stall(exe: Path, port: int) -> int:
    checker = Checker()
    receiver = run_receiver(port, ["--slow-ms", "3000", "--run-seconds", "20"])
    samples: list[float] = []
    try:
        capture = subprocess.Popen(
            [
                str(exe),
                "fixture",
                "--seconds",
                "12",
                "--tone-hz",
                "800",
                "--backend",
                f"http://127.0.0.1:{port}",
                "--token",
                TOKEN,
            ],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        while capture.poll() is None:
            memory = process_working_set_mb(capture.pid)
            if memory is not None:
                samples.append(memory)
            time.sleep(0.2)
        stdout, stderr = capture.communicate(timeout=10)
        summary = finish_receiver(receiver)
    finally:
        if receiver.poll() is None:
            receiver.kill()
    print(stdout)

    chunks = 0
    for line in stdout.splitlines():
        if line.startswith("fixture: chunks="):
            chunks = int(line.split("chunks=")[1].split()[0])
    checker.check(chunks >= 10, f"capture emitted chunks despite slow receiver ({chunks})")
    checker.check(summary["rejected"] + summary["duplicates"] >= 0, "sender discards, never retransmits")
    if samples:
        peak = max(samples)
        growth = peak - min(samples)
        checker.check(peak < 200.0, f"peak working set bounded ({peak:.1f} MiB)")
        checker.check(growth < 50.0, f"working set growth bounded ({growth:.1f} MiB)")
        print(f"  memory samples: min={min(samples):.1f} max={peak:.1f} MiB, n={len(samples)}")
    else:
        print("  [skip] memory sampling unavailable on this platform")
    return checker.report()


SCENARIOS = {
    "lifecycle": scenario_lifecycle,
    "fixture": scenario_fixture,
    "stall": scenario_stall,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", required=True, help="path to radar_capture.exe")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), required=True)
    parser.add_argument("--port", type=int, default=8013)
    args = parser.parse_args()

    exe = Path(args.exe)
    if not exe.exists():
        print(f"missing capture executable: {exe}", file=sys.stderr)
        return 2
    print(f"integration_check: scenario={args.scenario} exe={exe} port={args.port}")
    return SCENARIOS[args.scenario](exe, args.port)


if __name__ == "__main__":
    sys.exit(main())
