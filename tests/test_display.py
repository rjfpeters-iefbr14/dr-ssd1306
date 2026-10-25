from dr_ssd1306.server.display import DisplayWorker
from dr_ssd1306.server.model import Engine


class Device:
    def display(self, image):
        self.image = image

    def cleanup(self):
        pass


def test_failure_is_reported_then_retried(clock):
    engine = Engine(clock=clock)
    engine.update({"hardware_enabled": True})
    calls = []

    def factory(config):
        calls.append(config)
        if len(calls) == 1:
            raise OSError("I2C remote I/O error")
        return Device()

    worker = DisplayWorker(engine, factory, clock)
    worker.step()
    assert engine.snapshot()["hardware"]["status"] == "error"
    worker.step()
    assert len(calls) == 1
    clock.advance(5)
    worker.step()
    assert engine.snapshot()["hardware"]["status"] == "connected"
    engine.update({"hardware_enabled": False})
    worker.step()
    assert worker.device is None
    assert engine.snapshot()["hardware"]["status"] == "simulation"
