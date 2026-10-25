"""The display_ssd1306 plugin: an RTI-FSP's DR requests on this OLED.

The plugin API of the iec61850-websocket rti-demo, contract version 2: an
HTTP service under /plugin that the FSP connects to from its plugin
configuration,

    {"name": "display_ssd1306", "url": "http://<display>:8080/plugin"}

It runs in the display service and acts on its engine directly:

- an Operate on LD0/DWMX1.WMaxSpt (the power limit, W) below the baseline
  sets the requested reduction (baseline - limit) and starts the event;
  a new limit starts it again, a limit at or above the baseline ends it;
- the association and the FSP's stop restore and lose the engine's DR link;
- every poll_seconds it writes the simulated power (LD0/MMXU1.TotW.mag.f)
  and the limit the site applies (LD0/DWMX1.WMaxSpt.mxVal.f) into the
  FSP's model, through the FSP's POST /api/writevalue at its host_url, so
  they reach the SO in its ActualValues and Setpoints reports.

One FSP at a time: the most recent one that started it. Another FSP's
events and Operates are left alone, and an SO's too. After a restart of
this service, the first FSP to send an event or Operate is served, with
the default settings, until it starts the plugin again.

GET /plugin/attached describes the display for the HMI (decision 0025 of
the rti-demo): its state, power, applied limit and reduction.
Settings (from /start): poll_seconds, w_per_kw, min_change_w, power_ref,
applied_limit_ref. Its routes are the display's /api:
/api/plugins/display_ssd1306/state in the FSP is this service's
/api/state. GET /plugin/status and POST /plugin/resync are its own, on this
service only.
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import json
import logging
import time
from typing import Any
import urllib.error
import urllib.request

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ..server.model import Engine
from .mapping import (
    OPERATE_REF, Settings, attached_item, ctl_number, end_action, report_writes, requested_reduction_kw, write_body,
)

LOG = logging.getLogger(__name__)

API_VERSION = 2
NAME = "display_ssd1306"
# A write to the FSP; the poll runs apart from the events, so this only
# limits how long one poll waits for an FSP that doesn't answer.
HTTP_TIMEOUT = 2.0


class Host(BaseModel):
    name: str
    role: str
    host_url: str | None = None


class StartRequest(Host):
    settings: dict[str, Any] = Field(default_factory=dict)


class EventRequest(BaseModel):
    host: Host
    event: dict[str, Any]


class ControlRequest(BaseModel):
    host: Host
    obj_ref: str
    ctl_val: dict[str, Any] = Field(default_factory=dict)


def _version() -> str:
    try:
        return importlib.metadata.version("dr-ssd1306")
    except importlib.metadata.PackageNotFoundError:
        return ""


def _same(a: Host | None, b: Host) -> bool:
    return a is not None and (a.role, a.host_url) == (b.role, (b.host_url or "").rstrip("/"))


class DisplaySsd1306Plugin:
    def __init__(self, engine: Engine):
        self.engine = engine
        self.host: Host | None = None  # the FSP the values are written to
        self.settings = Settings()
        self._poller: asyncio.Task | None = None
        self._poll_lock = asyncio.Lock()
        # Set by control, applied once the FSP has answered the Operate.
        self._pending_limit: float | None = None
        self._reported: dict = {}
        self.last_request: dict | None = None
        self.last_error: str | None = None
        self.writes = 0

    # ---------- the plugin API ----------

    async def start(self, request: StartRequest) -> None:
        if request.role != "fsp":
            LOG.warning("display_ssd1306 belongs in an FSP; idle for the %s %s", request.role, request.host_url)
            return
        if not request.host_url:
            raise ValueError("host_url is needed: the FSP the display's values are written to")
        await self._serve(request, Settings.from_settings(request.settings))

    async def adopt(self, host: Host, event_type: str | None = None) -> None:
        """Serve this FSP when no FSP has started the display since it restarted.

        The FSP only calls /start when it starts or reloads the plugin, so
        after a restart of this service it would go on sending events and
        Operates that nothing acts on. Its settings went with the restart:
        the defaults apply until the FSP reloads the plugin.
        """
        if self.host is not None or host.role != "fsp" or not host.host_url or event_type == "ServerStopped":
            return
        LOG.info("%s wasn't started since the display restarted; serving it with the default settings", host.host_url)
        await self._serve(host, Settings())

    async def _serve(self, host: Host, settings: Settings) -> None:
        await self._stop_poller()
        self.host = Host(name=host.name, role=host.role, host_url=host.host_url.rstrip("/"))
        self.settings = settings
        self._reported.clear()
        self._pending_limit = None
        self.last_error = None
        LOG.info("Showing the DR requests of %s, writing its values there", self.host.host_url)
        self._poller = asyncio.create_task(self._poll_forever())

    async def stop(self, host: Host) -> None:
        if _same(self.host, host):
            await self._stop_poller()
            self.host = None

    def control(self, request: ControlRequest) -> None:
        """Remember the limit of an Operate from our FSP; the FSP's own check decides."""
        if not _same(self.host, request.host) or request.obj_ref != OPERATE_REF:
            return
        self._pending_limit = ctl_number(request.ctl_val)

    def on_event(self, request: EventRequest) -> None:
        if not _same(self.host, request.host):
            return
        event = request.event
        match event.get("type"):
            case "Associated":
                self._act("link-restored")
            case "ServerStopped":
                self._reported.clear()
                self._act("link-lost")
            case "OperateResponse" if event.get("success") and self._pending_limit is not None:
                limit, self._pending_limit = self._pending_limit, None
                self._apply_limit(limit)
            case "OperateResponse":
                self._pending_limit = None

    async def close(self) -> None:
        await self._stop_poller()

    # ---------- the engine ----------

    def _apply_limit(self, limit_w: float) -> None:
        """Start (or start again) the event a limit asks for, or end it."""
        state = self.engine.snapshot()
        reduction = requested_reduction_kw(limit_w, state, self.settings)
        try:
            if reduction > 0:
                self.engine.update({"requested_kw": reduction})
                self.engine.action("start")
                done = {"requested_kw": reduction, "action": "start"}
            else:
                action = end_action(state)
                if action:
                    self.engine.action(action)
                done = {"action": action}
        except (ValueError, OSError) as exc:
            # The FSP already answered the Operate; the display can only log it.
            self._fail(f"limit {limit_w} W: {exc}")
            return
        self.last_request = {"limit_w": limit_w, **done, "at": time.time()}

    def _act(self, action: str) -> None:
        try:
            self.engine.action(action)
        except ValueError as exc:
            self._fail(f"{action}: {exc}")

    # ---------- the FSP's model ----------

    async def _poll_forever(self) -> None:
        while True:
            await self.poll_once()
            await asyncio.sleep(self.settings.poll_seconds)

    async def poll_once(self) -> None:
        """Write what changed on the display into the FSP's model."""
        async with self._poll_lock:
            if self.host is None:
                return
            url = f"{self.host.host_url}/api/writevalue"
            for write in report_writes(self.engine.snapshot(), self._reported, self.settings):
                try:
                    await asyncio.to_thread(self._http, "POST", url, write_body(write))
                except Exception as exc:
                    # An error while the FSP's server isn't started: try again next poll.
                    self._fail(f"write {write['objRef']}: {exc}")
                    return
                self._reported[write["objRef"]] = write["value"]
                self.writes += 1
            self.last_error = None

    async def _stop_poller(self) -> None:
        if self._poller is not None:
            self._poller.cancel()
            try:
                await self._poller
            except asyncio.CancelledError:
                pass
            self._poller = None

    def _fail(self, message: str) -> None:
        if message != self.last_error:
            LOG.warning(message)
        self.last_error = message

    @staticmethod
    def _http(method: str, url: str, body: dict | None = None):
        """One blocking JSON request; run it with asyncio.to_thread."""
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(
            url, data=data, method=method,
            headers={"Content-Type": "application/json"} if data else {},
        )
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
                text = response.read()
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"HTTP {exc.code}: {exc.read().decode(errors='replace')[:200]}") from exc
        return json.loads(text) if text else None


def create_plugin_router(engine: Engine) -> APIRouter:
    """The plugin API under /plugin, acting on `engine`."""
    plugin = DisplaySsd1306Plugin(engine)
    router = APIRouter(prefix="/plugin", tags=["Plugin API (decision 0029)"])

    @router.get("", summary="Describe the plugin")
    def describe():
        return {
            "name": NAME,
            "version": _version(),
            "api": API_VERSION,
            "claims": [OPERATE_REF],
            "routes": "/api",
        }

    @router.post("/start", summary="Start serving an FSP")
    async def start(request: StartRequest):
        try:
            await plugin.start(request)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"ok": True}

    @router.post("/stop", summary="Stop serving an FSP")
    async def stop(host: Host):
        await plugin.stop(host)
        return {"ok": True}

    @router.post("/events", summary="Something happened in the FSP")
    async def events(request: EventRequest):
        await plugin.adopt(request.host, request.event.get("type"))
        plugin.on_event(request)
        return {"ok": True}

    @router.post("/control", status_code=204, summary="An Operate on the power limit")
    async def control(request: ControlRequest):
        await plugin.adopt(request.host)
        plugin.control(request)
        return Response(status_code=204)

    @router.get("/attached", summary="What the plugin attaches: the OLED (decision 0025)")
    def attached(request: Request):
        address = str(request.base_url).rstrip("/")
        return {"items": [attached_item(engine.snapshot(), plugin.last_error, address)]}

    @router.get("/status", summary="The FSP it writes to, the last request and writes")
    def status():
        return {
            "host": plugin.host.model_dump() if plugin.host else None,
            "operate_ref": OPERATE_REF,
            "last_request": plugin.last_request,
            "reported": plugin._reported,
            "writes": plugin.writes,
            "last_error": plugin.last_error,
        }

    @router.post("/resync", summary="Write all values to the FSP again")
    def resync():
        plugin._reported.clear()
        return {"ok": True}

    router.plugin = plugin  # for the app's shutdown and the tests
    return router
