"""Single display writer with lazy hardware imports and bounded retry frequency."""

import logging
import threading
import time

from .render import render

LOG = logging.getLogger(__name__)


def open_device(config):
    from luma.core.interface.serial import i2c
    from luma.oled.device import ssd1306

    serial = i2c(port=config["i2c_bus"], address=config["i2c_address"])
    try:
        device = ssd1306(serial, width=128, height=64, rotate=config["rotation"] // 90)
        device.contrast(config["contrast"])
        return device
    except Exception:
        serial.cleanup()
        raise


class DisplayWorker:
    def __init__(self, engine, factory=open_device, clock=time.monotonic):
        self.engine = engine
        self.factory = factory
        self.clock = clock
        self.device = None
        self.signature = None
        self.retry_at = 0
        self.stop_event = threading.Event()
        self.thread = None

    def close_device(self):
        if self.device is not None:
            try:
                self.device.cleanup()
            except Exception:
                LOG.debug("Display cleanup failed", exc_info=True)
            self.device = None

    def step(self):
        state = self.engine.snapshot()
        config = state["settings"]
        signature = tuple(config[key] for key in ("hardware_enabled", "i2c_bus", "i2c_address", "rotation", "contrast"))
        if signature != self.signature:
            self.close_device()
            self.signature = signature
            self.retry_at = 0
        if not config["hardware_enabled"]:
            self.engine.set_hardware("simulation")
            return
        if self.clock() < self.retry_at:
            return
        try:
            if self.device is None:
                self.device = self.factory(config)
            self.device.display(render(state))
            self.engine.set_hardware("connected")
        except Exception as exc:
            LOG.warning("OLED unavailable; retrying in 5 seconds: %s", exc)
            self.engine.set_hardware("error", f"{type(exc).__name__}: {exc}")
            self.close_device()
            self.retry_at = self.clock() + 5

    def _run(self):
        while not self.stop_event.is_set():
            self.step()
            self.stop_event.wait(0.5)
        self.close_device()

    def start(self):
        self.thread = threading.Thread(target=self._run, name="oled-writer", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)
