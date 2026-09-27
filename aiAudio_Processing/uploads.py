import asyncio

from fastapi import HTTPException, Request
from python_multipart import MultipartParser
from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import parse_options_header


MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_REQUEST_BYTES = MAX_FILE_BYTES + 64 * 1024
UPLOAD_TIMEOUT_SECONDS = 15


class MemoryWavPart:
    """One multipart file, parsed incrementally without temporary files."""

    def __init__(self):
        self.audio = bytearray()
        self.parts = 0
        self.complete = False
        self.headers = {}
        self.field = bytearray()
        self.value = bytearray()
        self.header_bytes = 0

    def on_part_begin(self):
        self.parts += 1
        if self.parts != 1:
            raise HTTPException(400, "Send exactly one WAV file in the 'file' field.")

    def on_header_field(self, data, start, end):
        self._header(self.field, data, start, end)

    def on_header_value(self, data, start, end):
        self._header(self.value, data, start, end)

    def _header(self, target, data, start, end):
        self.header_bytes += end - start
        if self.header_bytes > 16384:
            raise HTTPException(413, "Multipart headers are too large.")
        target.extend(data[start:end])

    def on_header_end(self):
        name = bytes(self.field).lower()
        if name in self.headers:
            raise HTTPException(400, "Duplicate multipart header.")
        self.headers[name] = bytes(self.value)
        self.field.clear()
        self.value.clear()

    def on_headers_finished(self):
        disposition, options = parse_options_header(self.headers.get(b"content-disposition", b""))
        if disposition != b"form-data" or options.get(b"name") != b"file" or not options.get(b"filename"):
            raise HTTPException(400, "Send a WAV file in the 'file' field.")

    def on_part_data(self, data, start, end):
        if len(self.audio) + end - start > MAX_FILE_BYTES:
            raise HTTPException(413, "Maximum file size is 5 MB.")
        self.audio.extend(data[start:end])

    def on_end(self):
        self.complete = True


async def read_wav_upload(request: Request):
    """Accept existing multipart clients and raw WAV clients; never call form()."""
    content_type, options = parse_options_header(request.headers.get("content-type", ""))
    multipart = content_type == b"multipart/form-data"
    if not multipart and content_type not in (b"audio/wav", b"audio/x-wav", b"application/octet-stream"):
        raise HTTPException(415, "Use multipart/form-data or audio/wav.")
    limit = MAX_REQUEST_BYTES if multipart else MAX_FILE_BYTES
    length = request.headers.get("content-length")
    if length is not None:
        if not length.isascii() or not length.isdecimal():
            raise HTTPException(400, "Invalid Content-Length.")
        # Bound conversion as well as the actual streamed bytes.
        if len(length) > 10 or int(length) > limit:
            raise HTTPException(413, "Upload exceeds the request size limit.")

    part = MemoryWavPart()
    parser = None
    if multipart:
        boundary = options.get(b"boundary")
        if not boundary or len(boundary) > 200:
            raise HTTPException(400, "Missing or invalid multipart boundary.")
        callbacks = {name: getattr(part, name) for name in (
            "on_part_begin", "on_header_field", "on_header_value", "on_header_end",
            "on_headers_finished", "on_part_data", "on_end",
        )}
        parser = MultipartParser(boundary, callbacks)
    total = 0
    try:
        async with asyncio.timeout(UPLOAD_TIMEOUT_SECONDS):
            async for chunk in request.stream():
                total += len(chunk)
                if total > limit:
                    raise HTTPException(413, "Upload exceeds the request size limit.")
                if parser is None:
                    part.on_part_data(chunk, 0, len(chunk))
                else:
                    parser.write(chunk)
        if parser is not None:
            parser.finalize()
            if not part.complete or part.parts != 1:
                raise HTTPException(400, "The multipart upload is incomplete.")
    except MultipartParseError as error:
        raise HTTPException(400, "Invalid multipart upload.") from error
    except TimeoutError as error:
        raise HTTPException(408, "Upload timed out.") from error
    if not part.audio:
        raise HTTPException(400, "The recording is empty.")
    return bytes(part.audio)
