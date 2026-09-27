import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import logging
import os
from pathlib import Path
import secrets
import sqlite3
from threading import Lock
from typing import Literal
import uuid

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from changes import ChangeBuffer
from classifier import SoundClassifier
from audio_processing import prepare_wav
from events import create_event, format_utc
from ingest import (
    CHUNK_BYTES,
    HEARTBEAT_LEASE_MS,
    STALE_CHUNK_SECONDS,
    CaptureRegistry,
    ChunkQueue,
    IngestError,
    chunk_age_seconds,
    parse_chunk,
)
from pipeline import DetectionPipeline
from playback import PlaybackConflict, PlaybackRegistry
from speech import LABEL_TEMPLATES, SpeechError, SpeechService
from storage import EventStore, SettingsStore
from uploads import read_wav_upload


logger = logging.getLogger(__name__)

ERROR_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    408: "TIMEOUT",
    409: "CONFLICT",
    413: "TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "SCHEMA_INVALID",
    429: "CAPACITY",
    503: "DEPENDENCY_UNAVAILABLE",
    504: "UPSTREAM_TIMEOUT",
}
RETRYABLE_STATUS = frozenset({ 408, 429, 503, 504 })


class ApiError(HTTPException):
    """Contract error carrying the canonical error code and retryable flag."""

    def __init__(self, status_code, code, message, retryable=False, headers=None):
        super().__init__(status_code=status_code, detail=message, headers=headers)
        self.code = code
        self.message = message
        self.retryable = retryable


def error_response(status_code, code, message, retryable, headers=None):
    return JSONResponse(
        status_code=status_code,
        content={
            "schema_version": 1,
            "error": {"code": code, "message": message, "retryable": retryable},
            "request_id": str(uuid.uuid4()),
        },
        headers=headers,
    )


def settings_payload(settings):
    return {"schema_version": 1, **asdict(settings)}


def parse_muted_until(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise ApiError(422, "SCHEMA_INVALID", "muted_until must be RFC 3339.") from None
    if parsed.tzinfo is None:
        raise ApiError(422, "SCHEMA_INVALID", "muted_until must include a timezone.")
    if parsed.astimezone(timezone.utc) > datetime.now(timezone.utc) + timedelta(hours=1):
        raise ApiError(422, "SCHEMA_INVALID", "muted_until is at most one hour ahead.")
    return format_utc(parsed)


async def read_chunk_body(request: Request) -> bytes:
    """Read the octet-stream body, enforcing the exact 32,000-byte contract."""
    expected = f"Chunk body must be exactly {CHUNK_BYTES} bytes."
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            declared_length = int(declared)
        except ValueError:
            raise ApiError(400, "BAD_REQUEST", "Invalid Content-Length header.") from None
        if declared_length > CHUNK_BYTES:
            raise ApiError(413, "TOO_LARGE", expected)
    body = bytearray()
    async for piece in request.stream():
        body.extend(piece)
        if len(body) > CHUNK_BYTES:
            raise ApiError(413, "TOO_LARGE", expected)
    if len(body) != CHUNK_BYTES:
        raise ApiError(413, "TOO_LARGE", expected)
    return bytes(body)


async def finish_in_thread(function, *args):
    """Do not release the inference gate while a cancelled request still runs."""
    work = asyncio.create_task(asyncio.to_thread(function, *args))
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(work)
            break
        except asyncio.CancelledError:
            if work.cancelled():
                raise
            cancelled = True
        except Exception:
            if cancelled:
                raise asyncio.CancelledError from None
            raise
    if cancelled:
        raise asyncio.CancelledError
    return result


def create_app(classifier_factory=SoundClassifier, db_path=None, capture_token=None,
               speech_service=None, playback_registry=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.classifier = None
        app.state.model_status = "loading"
        app.state.model_error = None
        app.state.inference_lock = Lock()
        path = db_path or os.environ.get("LOCAL_DB_PATH") or Path(__file__).parent / "data" / "events.sqlite3"
        retention_days = int(os.environ.get("RETENTION_DAYS", "1"))
        app.state.store = EventStore(path, retention_days=retention_days)
        app.state.settings_store = SettingsStore(path, retention_days=retention_days)
        app.state.changes = ChangeBuffer()
        app.state.registry = CaptureRegistry()
        app.state.playback = playback_registry or PlaybackRegistry()
        app.state.speech = speech_service or SpeechService.from_env()
        app.state.pipeline = DetectionPipeline(
            lambda: app.state.classifier,
            app.state.store,
            app.state.changes,
            app.state.registry,
            app.state.playback,
        )
        app.state.audio_queue = ChunkQueue(sink=app.state.pipeline.handle_chunk)
        app.state.audio_queue.start()
        stopped = asyncio.Event()

        def initialize_model():
            classifier = classifier_factory()
            classifier.warm_up()
            return classifier

        async def load_model():
            try:
                app.state.classifier = await finish_in_thread(initialize_model)
                app.state.model_status = "ready"
            except Exception:
                logger.exception("Model loading or warm-up failed")
                app.state.model_status = "error"
                app.state.model_error = "Model initialization failed. Check MODEL_DIR and installed dependencies, then restart."

        async def maintain_history():
            while not stopped.is_set():
                try:
                    await asyncio.wait_for(stopped.wait(), timeout=60)
                except TimeoutError:
                    try:
                        await finish_in_thread(app.state.store.purge)
                    except sqlite3.Error:
                        logger.exception("Local history cleanup failed")

        loader = asyncio.create_task(load_model())
        maintenance = asyncio.create_task(maintain_history())
        try:
            yield
        finally:
            stopped.set()
            app.state.audio_queue.stop()
            await maintenance
            await loader
            app.state.classifier = None

    app = FastAPI(title="Live Sound Radar", lifespan=lifespan)
    app.state.capture_token = capture_token if capture_token is not None else os.environ.get("CAPTURE_TOKEN", "")

    class HeartbeatRequest(BaseModel):
        model_config = ConfigDict(extra="forbid")

        schema_version: Literal[1]
        device_id: uuid.UUID
        stream_id: uuid.UUID | None
        state: Literal["stopped", "starting", "running", "error"]
        native_rate_hz: int | None = Field(gt=0)
        dropped_frames_total: int = Field(ge=0)
        error_code: str | None = Field(max_length=200)

    class SettingsChanges(BaseModel):
        model_config = ConfigDict(extra="forbid")

        capture_enabled: bool | None = None
        cloud_storage_enabled: bool | None = None
        analytics_enabled: bool | None = None
        speech_enabled: bool | None = None
        retention_days: int | None = None
        cooldown_seconds: int | None = None
        muted_until: str | None = None

    class UpdateSettingsRequest(BaseModel):
        model_config = ConfigDict(extra="forbid")

        schema_version: Literal[1]
        request_id: uuid.UUID
        expected_revision: int = Field(ge=0)
        changes: SettingsChanges

    class AcknowledgeRequest(BaseModel):
        model_config = ConfigDict(extra="forbid")

        schema_version: Literal[1]
        request_id: uuid.UUID

    class SpeechRequest(BaseModel):
        model_config = ConfigDict(extra="forbid")

        schema_version: Literal[1]
        request_id: uuid.UUID
        event_id: uuid.UUID

    class PlaybackRequest(BaseModel):
        model_config = ConfigDict(extra="forbid")

        schema_version: Literal[1]
        request_id: uuid.UUID
        state: Literal["started", "ended"]
        playback_id: uuid.UUID

    def require_capture_token(request: Request):
        expected = getattr(request.app.state, "capture_token", "")
        if not expected:
            return
        scheme, _, value = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not secrets.compare_digest(value.strip(), expected):
            raise ApiError(401, "UNAUTHORIZED", "Missing or invalid capture token.")

    def require_model_ready(request: Request):
        if request.app.state.model_status != "ready":
            raise ApiError(503, "MODEL_NOT_READY", "Model is not ready to accept audio.", retryable=True)

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request, exc):
        if isinstance(exc, ApiError):
            return error_response(exc.status_code, exc.code, exc.message, exc.retryable, exc.headers)
        return error_response(
            exc.status_code,
            ERROR_CODES.get(exc.status_code, "ERROR"),
            str(exc.detail),
            exc.status_code in RETRYABLE_STATUS,
            exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request, exc):
        return error_response(422, "SCHEMA_INVALID", "Request does not match the schema.", False)

    @app.get("/health/live")
    def live():
        return {"status": "alive"}

    @app.get("/health")
    @app.get("/health/ready")
    def ready():
        result = {"status": app.state.model_status, "model": "YAMNet"}
        if app.state.model_error:
            result["error"] = app.state.model_error
        return JSONResponse(result, status_code=200 if app.state.model_status == "ready" else 503)

    def process_recording(file_bytes):
        try:
            audio = prepare_wav(file_bytes)
        except (ValueError, OSError) as error:
            raise HTTPException(400, str(error)) from error
        try:
            prediction = app.state.classifier.classify(audio)
        except Exception as error:
            logger.exception("Local inference failed")
            app.state.model_status = "error"
            app.state.model_error = "Inference failed. Check the server log and restart."
            raise HTTPException(503, "Local inference is unavailable.") from error
        if prediction is None:
            return None
        event = create_event(prediction)
        # This endpoint accepts test recordings, not a live capture stream.
        event["source"] = "fixture"
        try:
            app.state.store.save_event(event)
        except sqlite3.Error as error:
            logger.exception("Local event persistence failed")
            raise HTTPException(503, "Local history is unavailable.") from error
        return event

    @app.post("/classify-file", responses={204: {"description": "No eligible detection."}}, openapi_extra={
        "requestBody": {"required": True, "content": {
            "multipart/form-data": {"schema": {"type": "object", "required": ["file"],
                "properties": {"file": {"type": "string", "format": "binary"}}}},
            "audio/wav": {"schema": {"type": "string", "format": "binary"}},
        }},
    })
    async def classify_file(request: Request):
        if app.state.model_status != "ready":
            raise HTTPException(503, "Model is not ready. Check /health/ready.")
        # Reject concurrent uploads before reading their bodies as well as
        # serializing inference. The complete accepted request stays in RAM.
        if not app.state.inference_lock.acquire(blocking=False):
            raise HTTPException(503, "Classifier is busy. Try again shortly.")
        try:
            file_bytes = await read_wav_upload(request)
            event = await finish_in_thread(process_recording, file_bytes)
            return event if event is not None else Response(status_code=204)
        finally:
            app.state.inference_lock.release()

    @app.post("/v1/capture/heartbeat")
    def capture_heartbeat(
        request: Request,
        body: HeartbeatRequest,
        _token: None = Depends(require_capture_token),
    ):
        settings = request.app.state.settings_store.get()
        request.app.state.registry.record_heartbeat(
            device_id=str(body.device_id),
            stream_id=str(body.stream_id) if body.stream_id is not None else None,
            state=body.state,
            native_rate_hz=body.native_rate_hz,
            dropped_frames_total=body.dropped_frames_total,
            error_code=body.error_code,
        )
        return {
            "schema_version": 1,
            "desired_capture": settings.capture_enabled,
            "lease_ms": HEARTBEAT_LEASE_MS,
            "settings_revision": settings.revision,
        }

    @app.post("/v1/audio/chunks")
    async def audio_chunks(
        request: Request,
        _token: None = Depends(require_capture_token),
        _ready: None = Depends(require_model_ready),
    ):
        state = request.app.state
        content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
        if content_type != "application/octet-stream":
            raise ApiError(415, "UNSUPPORTED_MEDIA_TYPE", "Content-Type must be application/octet-stream.")
        body = await read_chunk_body(request)
        try:
            chunk = parse_chunk(request.headers, body)
        except IngestError as error:
            raise ApiError(error.status_code, error.code, error.message, error.retryable) from error
        try:
            outcome = state.registry.admit(chunk)
        except IngestError as error:
            raise ApiError(error.status_code, error.code, error.message, error.retryable) from error

        payload = {
            "schema_version": 1,
            "stream_id": chunk.stream_id,
            "chunk_seq": chunk.chunk_seq,
            "status": outcome,
            "queue_depth": state.audio_queue.qsize(),
        }
        if outcome == "duplicate":
            return JSONResponse(status_code=200, content=payload)
        if chunk_age_seconds(chunk) > STALE_CHUNK_SECONDS:
            # Discard rather than infer on a window that is no longer contiguous.
            state.registry.mark_gap(chunk)
            return JSONResponse(status_code=202, content=payload)
        if not state.audio_queue.submit(chunk):
            state.registry.mark_gap(chunk)
            raise ApiError(429, "CAPACITY", "Audio queue is full.", retryable=True)
        payload["queue_depth"] = state.audio_queue.qsize()
        return JSONResponse(status_code=202, content=payload)

    @app.get("/v1/state")
    def system_state(request: Request, after: int | None = None, instance_id: str | None = None):
        state = request.app.state
        changes, cursor, reset_required = state.changes.poll(after, instance_id)
        settings = state.settings_store.get()
        return {
            "schema_version": 1,
            "instance_id": state.changes.instance_id,
            "cursor": cursor,
            "reset_required": reset_required,
            "status": {
                "capture": state.registry.aggregate_state(),
                "model": state.model_status,
                "cloud": "disabled" if not settings.cloud_storage_enabled else "offline",
                "export_pending": 0,
                "export_dropped": 0,
                "audio_gaps": state.pipeline.audio_gaps,
            },
            "changes": changes,
        }

    @app.get("/v1/events")
    def list_history(limit: int = 50, before: str | None = None):
        if not 1 <= limit <= 100:
            raise ApiError(422, "SCHEMA_INVALID", "limit must be between 1 and 100.")
        try:
            items, next_cursor = app.state.store.get_live_events(limit=limit, before=before)
        except ValueError as error:
            raise ApiError(422, "SCHEMA_INVALID", "Invalid cursor.") from error
        return {"schema_version": 1, "items": items, "next_cursor": next_cursor}

    @app.post("/v1/events/{event_id}/ack")
    def acknowledge_event(event_id: str, body: AcknowledgeRequest):
        try:
            validated = str(uuid.UUID(event_id))
        except ValueError:
            raise ApiError(422, "SCHEMA_INVALID", "event_id must be a UUID.") from None
        acknowledged = app.state.store.acknowledge(validated)
        if acknowledged is None:
            raise ApiError(404, "NOT_FOUND", "Unknown event.")
        acknowledged_at, created = acknowledged
        if created:
            app.state.changes.append(
                "event.acknowledged",
                {"event_id": validated, "acknowledged_at": acknowledged_at},
                event_id=validated,
            )
        return {"schema_version": 1, "event_id": validated, "acknowledged_at": acknowledged_at}

    @app.post("/v1/speech")
    def generate_speech(request: Request, body: SpeechRequest):
        state = request.app.state
        if not state.settings_store.get().speech_enabled:
            raise ApiError(403, "FORBIDDEN", "Speech is disabled in settings.")
        event = state.store.get_event(str(body.event_id))
        if event is None:
            raise ApiError(404, "NOT_FOUND", "Unknown event.")
        occurred = event.get("occurred_at")
        try:
            occurred_at = datetime.fromisoformat(occurred.replace("Z", "+00:00"))
        except (AttributeError, ValueError):
            raise ApiError(409, "CONFLICT", "The event time is unavailable.") from None
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - occurred_at.astimezone(timezone.utc)).total_seconds()
        if age > 60:
            raise ApiError(409, "CONFLICT", "The event is too old for speech.")
        template_id = LABEL_TEMPLATES.get(event.get("label"))
        if template_id is None:
            raise ApiError(422, "SCHEMA_INVALID", "Unsupported event label.")
        try:
            audio, cached = state.speech.synthesize(template_id)
        except SpeechError as error:
            raise ApiError(error.status_code, error.code, error.message, error.retryable) from error
        headers = {"Cache-Control": "no-store"}
        if cached:
            headers["X-Speech-Cached"] = "true"
        return Response(content=audio, media_type="audio/mpeg", headers=headers)

    @app.post("/v1/playback")
    def register_playback(request: Request, body: PlaybackRequest):
        try:
            if body.state == "started":
                request.app.state.playback.start(str(body.playback_id))
            else:
                request.app.state.playback.end(str(body.playback_id))
        except PlaybackConflict as error:
            raise ApiError(409, "CONFLICT", "Another speech playback is active.") from error
        return {"schema_version": 1, "playback_id": str(body.playback_id), "state": body.state}

    @app.get("/v1/settings")
    def get_settings():
        return settings_payload(app.state.settings_store.get())

    @app.patch("/v1/settings")
    def patch_settings(request: Request, body: UpdateSettingsRequest):
        state = request.app.state
        current = state.settings_store.get()
        if body.expected_revision != current.revision:
            raise ApiError(409, "CONFLICT", "Settings revision is stale.")
        changes = body.changes.model_dump(exclude_unset=True)
        if not changes:
            raise ApiError(422, "SCHEMA_INVALID", "At least one setting must change.")
        for name, value in changes.items():
            if name == "retention_days" and value not in (1, 7):
                raise ApiError(422, "SCHEMA_INVALID", "retention_days must be 1 or 7.")
            if name == "cooldown_seconds" and (value is None or not 5 <= value <= 60):
                raise ApiError(422, "SCHEMA_INVALID", "cooldown_seconds must be between 5 and 60.")
            if name == "muted_until":
                changes[name] = None if value is None else parse_muted_until(value)
            elif value is None:
                raise ApiError(422, "SCHEMA_INVALID", f"{name} cannot be null.")
        cloud = changes.get("cloud_storage_enabled", current.cloud_storage_enabled)
        analytics = changes.get("analytics_enabled", current.analytics_enabled)
        if analytics and not cloud:
            raise ApiError(422, "SCHEMA_INVALID", "Analytics requires cloud storage.")
        updated = state.settings_store.update(changes)
        payload = settings_payload(updated)
        state.changes.append("settings.changed", {"settings": payload})
        network_changed = any(
            name in changes for name in ("cloud_storage_enabled", "analytics_enabled", "speech_enabled")
        )
        return {**payload, "cloud_sync": "pending" if network_changed else "not_needed"}

    @app.get("/events")
    def list_events():
        try:
            return {"events": app.state.store.get_events()}
        except sqlite3.Error as error:
            raise HTTPException(503, "Local history is unavailable.") from error

    dist_dir = Path(__file__).resolve().parent.parent / "web" / "dist"
    if dist_dir.is_dir():
        app.mount("/", StaticFiles(directory=dist_dir, html=True), name="dashboard")

    return app


app = create_app()
