"""FastAPI web service for a trusted local demonstration network; mounts the RTI-FSP plugin API."""

from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
import hmac
from importlib.resources import files
from io import BytesIO
import json
import logging
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from ..plugin import create_plugin_router
from .display import DisplayWorker
from .logs import quiet_polls
from .model import Engine
from .render import colorize, render

LOG = logging.getLogger(__name__)
MAX_BODY = 8192
SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    # Everything is packaged locally; no remote assets or scripts.
    "Content-Security-Policy": "default-src 'self'; img-src 'self' blob:; script-src 'self' 'unsafe-inline'; "
                               "style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'",
}
ACTIONS = ("ready", "start", "schedule", "complete", "link-lost", "link-restored")


def _error(code: int, message: str, headers: dict | None = None) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=code, headers=headers)


def _open(path: str) -> bool:
    """Routes without the password: the Docker healthcheck, and the FSP, which can't sign in."""
    return path == "/health" or path == "/plugin" or path.startswith("/plugin/")


def create_app(engine: Engine | None = None, *, password: str | None = None, worker: DisplayWorker | None = None):
    engine = engine or Engine()
    # The plugin API the RTI-FSP connects to (decision 0003).
    plugin_router = create_plugin_router(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Here, not before uvicorn.run, so it survives uvicorn's logging setup.
        quiet_polls()
        if worker is not None:
            worker.start()
        try:
            yield
        finally:
            await plugin_router.plugin.close()
            if worker is not None:
                await asyncio.to_thread(worker.stop)

    app = FastAPI(title="DR SSD1306", version="0.2.0", lifespan=lifespan)
    app.state.engine = engine
    app.include_router(plugin_router)
    app.state.plugin = plugin_router.plugin
    expected = None if password is None else "Basic " + base64.b64encode(("demo:" + password).encode()).decode()

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if expected is not None and not _open(request.url.path):
            given = request.headers.get("Authorization", "")
            if not hmac.compare_digest(given.encode(), expected.encode()):
                response = _error(401, "Authentication required", {"WWW-Authenticate": 'Basic realm="DR SSD1306"'})
                response.headers.update(SECURITY_HEADERS)
                return response
        if request.method == "POST" and request.url.path.startswith("/api/"):
            # JSON-only writes plus same-origin checks block cross-site form/fetch writes.
            origin = request.headers.get("Origin")
            if (origin and urlsplit(origin).netloc != request.headers.get("Host")) \
                    or request.headers.get("Sec-Fetch-Site") == "cross-site":
                response = _error(403, "Cross-origin writes are not allowed")
            elif request.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
                response = _error(415, "Use Content-Type: application/json")
            else:
                response = await call_next(request)
        else:
            response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    async def payload(request: Request):
        body = await request.body()
        if not 0 < len(body) <= MAX_BODY:
            raise ValueError(f"JSON body must contain 1–{MAX_BODY} bytes")
        return json.loads(body)

    def answer(fn) -> JSONResponse:
        try:
            return JSONResponse(fn())
        except (ValueError, UnicodeError) as exc:
            return _error(400, str(exc))
        except OSError:
            LOG.exception("Unable to persist settings")
            return _error(500, "Could not save settings; check the configuration directory permissions")

    @app.get("/", response_class=HTMLResponse)
    def index():
        return files("dr_ssd1306.server").joinpath("static/index.html").read_text(encoding="utf-8")

    @app.get("/api/state")
    def state():
        return engine.snapshot()

    @app.get("/api/settings")
    def settings():
        return engine.snapshot()["settings"]

    @app.post("/api/settings")
    async def update_settings(request: Request):
        try:
            patch = await payload(request)
        except (ValueError, UnicodeError) as exc:
            return _error(400, str(exc))
        return answer(lambda: engine.update(patch))

    @app.post("/api/action")
    async def action(request: Request):
        try:
            body = await payload(request)
            if not isinstance(body, dict) or set(body) != {"action"} or not isinstance(body["action"], str):
                raise ValueError(f'Use {{"action": "start"}}, or one of {", ".join(ACTIONS)}')
        except (ValueError, UnicodeError) as exc:
            return _error(400, str(exc))
        return answer(lambda: engine.action(body["action"]))

    @app.get("/api/screen.png")
    def screen(raw: str | None = None):
        current = engine.snapshot()
        image = render(current)
        if raw != "1":
            image = colorize(image, current["settings"]["preview_palette"], current["settings"]["rotation"])
        stream = BytesIO()
        image.save(stream, format="PNG")
        return Response(stream.getvalue(), media_type="image/png")

    @app.get("/health")
    def health():
        return {"ok": True, "hardware": engine.snapshot()["hardware"]}

    return app
