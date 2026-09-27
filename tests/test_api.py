import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from api import create_app, finish_in_thread
from uploads import MAX_FILE_BYTES, MAX_REQUEST_BYTES


class FakeClassifier:
    def warm_up(self):
        pass

    def classify(self, audio):
        return {"label": "knock", "score": .9}


def wait_ready(client):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get("/health/ready")
        if response.status_code == 200:
            return
        if response.json()["status"] == "error":
            pytest.fail(response.text)
        time.sleep(.01)
    pytest.fail("Model did not become ready")


def test_loading_warmup_and_failure_are_visible(tmp_path):
    release = Event()
    class SlowClassifier(FakeClassifier):
        def warm_up(self):
            assert release.wait(5)
    with TestClient(create_app(SlowClassifier, tmp_path / "slow.sqlite3")) as client:
        try:
            assert client.get("/health/live").status_code == 200
            assert client.get("/health/ready").json()["status"] == "loading"
            assert client.post("/classify-file").status_code == 503
        finally:
            release.set()
        wait_ready(client)
    class FailedClassifier(FakeClassifier):
        def warm_up(self):
            raise RuntimeError("sensitive internal detail")
    with TestClient(create_app(FailedClassifier, tmp_path / "failed.sqlite3")) as client:
        deadline = time.monotonic() + 5
        while client.get("/health/ready").json()["status"] == "loading" and time.monotonic() < deadline:
            time.sleep(.01)
        response = client.get("/health")
        assert response.status_code == 503
        assert response.json()["status"] == "error"
        assert "sensitive" not in response.text
        assert client.get("/health/live").status_code == 200
        assert client.get("/events").json() == {"events": []}


def test_raw_and_multipart_uploads_work_without_spooling(tmp_path, make_wav, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Raw audio must never spool to a temporary file")
    monkeypatch.setattr("starlette.formparsers.SpooledTemporaryFile", forbidden)
    with TestClient(create_app(FakeClassifier, tmp_path / "events.sqlite3")) as client:
        wait_ready(client)
        response = client.post("/classify-file", files={"file": ("fixture.wav", make_wav(), "audio/wav")})
        assert response.status_code == 200
        assert response.json()["source"] == "fixture"
        response = client.post("/classify-file", content=make_wav(), headers={"Content-Type": "audio/wav"})
        assert response.status_code == 200
        assert len(client.get("/events").json()["events"]) == 2
        operation = client.get("/openapi.json").json()["paths"]["/classify-file"]["post"]
        assert "204" in operation["responses"]
        assert operation["requestBody"]["content"]["multipart/form-data"]["schema"]["required"] == ["file"]


def test_no_detection_returns_204_and_does_not_write_history(tmp_path, make_wav):
    class NoDetection(FakeClassifier):
        def classify(self, audio):
            return None
    with TestClient(create_app(NoDetection, tmp_path / "events.sqlite3")) as client:
        wait_ready(client)
        response = client.post("/classify-file", files={"file": ("test.wav", make_wav())})
        assert response.status_code == 204
        assert response.content == b""
        assert client.get("/events").json() == {"events": []}


def test_multipart_file_limit_applies_before_decoding(tmp_path):
    with TestClient(create_app(FakeClassifier, tmp_path / "events.sqlite3")) as client:
        wait_ready(client)
        response = client.post("/classify-file", files={"file": ("large.wav", bytes(MAX_FILE_BYTES + 1))})
        assert response.status_code == 413
        assert client.get("/events").json() == {"events": []}


def test_inference_failure_updates_readiness_without_stopping_history(tmp_path, make_wav):
    class BrokenClassifier(FakeClassifier):
        def classify(self, audio):
            raise RuntimeError("private model diagnostic")
    with TestClient(create_app(BrokenClassifier, tmp_path / "events.sqlite3")) as client:
        wait_ready(client)
        response = client.post("/classify-file", files={"file": ("test.wav", make_wav())})
        assert response.status_code == 503
        assert "private" not in response.text
        assert client.get("/health/ready").json()["status"] == "error"
        assert client.get("/health/live").status_code == 200
        assert client.get("/events").json() == {"events": []}


def test_bad_uploads_release_gate_and_write_no_events(tmp_path, make_wav):
    with TestClient(create_app(FakeClassifier, tmp_path / "events.sqlite3")) as client:
        wait_ready(client)
        cases = [
            ({"content": b"bad", "headers": {"Content-Type": "audio/wav"}}, 400),
            ({"content": b"bad", "headers": {"Content-Type": "text/plain"}}, 415),
            ({"content": b"", "headers": {"Content-Type": "audio/wav", "Content-Length": str(MAX_FILE_BYTES + 1)}}, 413),
            ({"files": {"wrong": ("a.wav", make_wav())}}, 400),
            ({"files": [("file", ("a.wav", make_wav())), ("file", ("b.wav", make_wav()))]}, 400),
            ({"content": b"--x\r\n", "headers": {"Content-Type": "multipart/form-data; boundary=x"}}, 400),
        ]
        for kwargs, status in cases:
            assert client.post("/classify-file", **kwargs).status_code == status
            assert client.get("/events").json() == {"events": []}
        assert client.post("/classify-file", files={"file": ("valid.wav", make_wav())}).status_code == 200


def test_fragmented_chunked_multipart_and_stream_size_limit(tmp_path, make_wav):
    async def run():
        app = create_app(FakeClassifier, tmp_path / "events.sqlite3")
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                while app.state.model_status == "loading":
                    await asyncio.sleep(.01)
                body = b'--abc\r\nContent-Disposition: form-data; name="file"; filename="a.wav"\r\n\r\n' + make_wav() + b'\r\n--abc--\r\n'
                async def fragmented():
                    for offset in range(0, len(body), 13):
                        yield body[offset:offset + 13]
                response = await client.post("/classify-file", content=fragmented(), headers={"Content-Type": "multipart/form-data; boundary=abc"})
                assert response.status_code == 200
                async def oversized():
                    for _ in range(MAX_REQUEST_BYTES // 65536 + 2):
                        yield bytes(65536)
                response = await client.post("/classify-file", content=oversized(), headers={"Content-Type": "audio/wav"})
                assert response.status_code == 413
                assert len((await client.get("/events")).json()["events"]) == 1
    asyncio.run(run())


def test_upload_timeout_releases_gate(tmp_path, make_wav, monkeypatch):
    monkeypatch.setattr("uploads.UPLOAD_TIMEOUT_SECONDS", .01)
    async def run():
        app = create_app(FakeClassifier, tmp_path / "events.sqlite3")
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                while app.state.model_status == "loading":
                    await asyncio.sleep(.01)
                async def slow():
                    yield b"start"
                    await asyncio.sleep(.1)
                    yield b"end"
                response = await client.post("/classify-file", content=slow(), headers={"Content-Type": "audio/wav"})
                assert response.status_code == 408
                response = await client.post("/classify-file", content=make_wav(), headers={"Content-Type": "audio/wav"})
                assert response.status_code == 200
    asyncio.run(run())


def test_inference_does_not_block_health_and_concurrent_upload_is_rejected(tmp_path, make_wav):
    entered, release = Event(), Event()
    class SlowClassifier(FakeClassifier):
        def classify(self, audio):
            entered.set()
            assert release.wait(5)
            return super().classify(audio)
    with TestClient(create_app(SlowClassifier, tmp_path / "events.sqlite3")) as client, ThreadPoolExecutor() as pool:
        wait_ready(client)
        future = pool.submit(client.post, "/classify-file", content=make_wav(), headers={"Content-Type": "audio/wav"})
        try:
            assert entered.wait(5)
            assert client.get("/health/ready").status_code == 200
            assert client.post("/classify-file").status_code == 503
        finally:
            release.set()
        assert future.result(timeout=5).status_code == 200


def test_cancelled_request_waits_for_inference_thread():
    async def run():
        entered, release, finished = Event(), Event(), Event()
        def work():
            entered.set()
            assert release.wait(5)
            finished.set()
        task = asyncio.create_task(finish_in_thread(work))
        while not entered.is_set():
            await asyncio.sleep(.01)
        task.cancel()
        await asyncio.sleep(.01)
        assert not task.done()
        task.cancel()  # Repeated cancellation must not free the gate either.
        await asyncio.sleep(.01)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set()
    asyncio.run(run())
