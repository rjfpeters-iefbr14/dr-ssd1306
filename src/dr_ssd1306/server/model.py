"""Validated settings and a clock-driven, thread-safe demonstration engine."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, fields
import json
import math
import os
from pathlib import Path
import re
import tempfile
import threading
import time


@dataclass(frozen=True)
class Settings:
    event_id: str = "DR-01"
    requested_kw: float = 2.0
    baseline_kw: float = 5.0
    demand_kw: float = 3.2
    duration_seconds: int = 900
    schedule_delay_seconds: int = 30
    preview_palette: str = "yellow-blue"
    hardware_enabled: bool = False
    i2c_bus: int = 1
    i2c_address: int = 60
    rotation: int = 0
    contrast: int = 160

    @classmethod
    def validated(cls, data: dict, base: Settings | None = None) -> Settings:
        if not isinstance(data, dict):
            raise ValueError("Settings must be a JSON object")
        unknown = set(data) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError("Unknown settings: " + ", ".join(sorted(unknown)))
        values = asdict(base or cls()) | data
        if not isinstance(values["event_id"], str) or not re.fullmatch(r"[A-Z0-9-]{1,7}", values["event_id"]):
            raise ValueError("event_id must contain 1–7 uppercase letters, digits or hyphens")
        for name in ("requested_kw", "baseline_kw", "demand_kw"):
            value = values[name]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 99.9:
                raise ValueError(f"{name} must be finite and between 0 and 99.9 kW")
            values[name] = round(float(value), 1)
        for name, low, high in (("duration_seconds", 1, 5999), ("schedule_delay_seconds", 0, 5999), ("i2c_bus", 0, 255), ("i2c_address", 3, 119), ("contrast", 0, 255)):
            if type(values[name]) is not int or not low <= values[name] <= high:
                raise ValueError(f"{name} must be an integer between {low} and {high}")
        if type(values["rotation"]) is not int or values["rotation"] not in (0, 180):
            raise ValueError("rotation must be 0 or 180 degrees")
        if type(values["hardware_enabled"]) is not bool:
            raise ValueError("hardware_enabled must be true or false")
        if values["preview_palette"] not in ("white", "blue", "yellow-blue"):
            raise ValueError("preview_palette must be white, blue or yellow-blue")
        return cls(**values)


def save_settings(path: Path, settings: Settings) -> None:
    """Commit a complete config atomically; never leave a partial JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".settings-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(asdict(settings), stream, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


class Engine:
    def __init__(self, path: Path | None = None, clock=time.monotonic):
        self.path = path
        self.clock = clock
        self.lock = threading.RLock()
        self.settings = Settings.validated(json.loads(path.read_text())) if path and path.exists() else Settings()
        self.mode = "ready"
        self.link_ok = True
        self.link_lost_at = None
        self.stale_reduction_kw = 0.0
        self.stale_demand_kw = 0.0
        self.scheduled_at = None
        self.started_at = None
        self.ends_at = None
        self.integral_kw_seconds = 0.0
        self.active_seconds = 0.0
        self.last_update = self.clock()
        self.history = deque([self.settings.baseline_kw], maxlen=32)
        self.last_sample = self.last_update - 1
        self.hardware = {"status": "simulation", "error": None}

    def _reduction(self):
        return max(0.0, self.settings.baseline_kw - self.settings.demand_kw)

    def _start(self, now):
        self.mode = "active"
        self.started_at = now
        self.ends_at = now + self.settings.duration_seconds
        self.scheduled_at = None
        self.integral_kw_seconds = self.active_seconds = 0.0
        self.last_update = now
        self.history.clear()
        self.history.append(self.settings.baseline_kw)

    def _advance(self, now):
        if self.mode == "scheduled" and now >= self.scheduled_at:
            self._start(self.scheduled_at)
        if self.mode == "active":
            until = min(now, self.ends_at)
            elapsed = max(0.0, until - self.last_update)
            self.integral_kw_seconds += self._reduction() * elapsed
            self.active_seconds += elapsed
            if now >= self.ends_at:
                self.mode = "done"
        self.last_update = now
        if now - self.last_sample >= 1:
            self.history.append(self.settings.demand_kw if self.mode in ("active", "done") else self.settings.baseline_kw)
            self.last_sample = now

    def update(self, patch):
        with self.lock:
            candidate = Settings.validated(patch, self.settings)
            if candidate.requested_kw <= 0 and self.mode in ("active", "scheduled"):
                raise ValueError("An activation requires a positive requested reduction")
            # Persist before changing live state; storage failure leaves settings intact.
            if self.path:
                save_settings(self.path, candidate)
            now = self.clock()
            self._advance(now)
            self.settings = candidate
            # Timing edits configure the next activation; current deadlines stay stable.
            return self.snapshot()

    def action(self, action):
        with self.lock:
            if action not in ("ready", "start", "schedule", "complete", "link-lost", "link-restored"):
                raise ValueError("Unknown action")
            now = self.clock()
            self._advance(now)
            if action in ("start", "schedule"):
                if not self.link_ok:
                    raise ValueError("Restore the demo link before activating")
                if self.settings.requested_kw <= 0:
                    raise ValueError("Set a positive requested reduction before activating")
            if action == "start":
                self._start(now)
            elif action == "schedule":
                self.mode = "scheduled"
                self.scheduled_at = now + self.settings.schedule_delay_seconds
                self.started_at = self.ends_at = None
                self.integral_kw_seconds = self.active_seconds = 0.0
            elif action == "complete":
                if self.mode != "active":
                    raise ValueError("Only an active event can be completed")
                self.mode = "done"
                self.ends_at = now
            elif action == "ready":
                self.mode = "ready"
                self.scheduled_at = self.started_at = self.ends_at = None
                self.integral_kw_seconds = self.active_seconds = 0.0
            elif action == "link-lost" and self.link_ok:
                self.link_ok = False
                self.link_lost_at = now
                self.stale_reduction_kw = self._reduction() if self.mode == "active" else (self.integral_kw_seconds / self.active_seconds if self.mode == "done" and self.active_seconds else 0.0)
                self.stale_demand_kw = self.settings.demand_kw
            elif action == "link-restored":
                self.link_ok = True
                self.link_lost_at = None
            return self.snapshot()

    def snapshot(self):
        with self.lock:
            now = self.clock()
            self._advance(now)
            avg = self.integral_kw_seconds / self.active_seconds if self.active_seconds else self._reduction()
            measured = avg if self.mode == "done" else (self._reduction() if self.mode == "active" else 0.0)
            if not self.link_ok:
                measured = self.stale_reduction_kw
            pct = measured / self.settings.requested_kw * 100 if self.settings.requested_kw else 0
            return {
                "settings": asdict(self.settings), "mode": self.mode,
                "display_state": self.mode if self.link_ok else "lost",
                "link_ok": self.link_ok,
                "delivered_kw": round(measured, 1), "average_kw": round(avg, 1),
                "fulfilment_percent": round(pct),
                "remaining_seconds": max(0, math.ceil((self.ends_at or now) - now)),
                "starts_in_seconds": max(0, math.ceil((self.scheduled_at or now) - now)),
                "stale_seconds": int(now - self.link_lost_at) if self.link_lost_at is not None else 0,
                "history_kw": list(self.history), "hardware": self.hardware.copy(),
                "simulation": True,
            }

    def set_hardware(self, status, error=None):
        with self.lock:
            self.hardware = {"status": status, "error": error}
