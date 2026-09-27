import asyncio
from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path
import sqlite3
from threading import Lock

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from classifier import SoundClassifier
from audio_processing import prepare_wav
from events import create_event
from storage import EventStore
from uploads import read_wav_upload


logger = logging.getLogger(__name__)


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


def create_app(classifier_factory=SoundClassifier, db_path=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.classifier = None
        app.state.model_status = "loading"
        app.state.model_error = None
        app.state.inference_lock = Lock()
        path = db_path or os.environ.get("LOCAL_DB_PATH") or Path(__file__).parent / "data" / "events.sqlite3"
        app.state.store = EventStore(path, retention_days=int(os.environ.get("RETENTION_DAYS", "1")))
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
            await maintenance
            await loader
            app.state.classifier = None

    app = FastAPI(title="Live Sound Radar", lifespan=lifespan)

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

    @app.get("/events")
    def list_events():
        try:
            return {"events": app.state.store.get_events()}
        except sqlite3.Error as error:
            raise HTTPException(503, "Local history is unavailable.") from error

    return app


app = create_app()
