from pathlib import Path

import pytest

from dr_ssd1306.server.model import Engine


@pytest.fixture
def engine(clock):
    return Engine(clock=clock)


def test_timed_activation_and_weighted_average(engine, clock):
    engine.update({"duration_seconds": 20})
    engine.action("start")
    clock.advance(10)
    engine.update({"demand_kw": 4.0})  # first 10 s at 1.8; next 10 at 1.0
    clock.advance(11)
    result = engine.snapshot()
    assert result["mode"] == "done"
    assert result["average_kw"] == pytest.approx(1.4)
    assert result["fulfilment_percent"] == 70
    assert result["remaining_seconds"] == 0


def test_delayed_tick_does_not_extend_scheduled_event(engine, clock):
    engine.update({"schedule_delay_seconds": 5, "duration_seconds": 10})
    engine.action("schedule")
    clock.advance(20)
    assert engine.snapshot()["mode"] == "done"
    assert engine.active_seconds == 10


def test_link_loss_freezes_display_but_timer_continues(engine, clock):
    engine.update({"duration_seconds": 10})
    engine.action("start")
    engine.action("link-lost")
    engine.update({"demand_kw": 4.0})
    clock.advance(12)
    snapshot = engine.snapshot()
    assert snapshot["display_state"] == "lost"
    assert snapshot["delivered_kw"] == 1.8
    assert snapshot["stale_seconds"] == 12
    assert snapshot["mode"] == "done"
    with pytest.raises(ValueError):
        engine.action("start")
    engine.action("link-restored")
    assert engine.snapshot()["display_state"] == "done"


def test_timing_edits_do_not_reset_running_timer(engine, clock):
    engine.update({"duration_seconds": 10})
    engine.action("start")
    clock.advance(2)
    engine.update({"duration_seconds": 100})
    assert engine.snapshot()["remaining_seconds"] == 8


@pytest.mark.parametrize("patch", [
    {"demand_kw": float("nan")}, {"requested_kw": True}, {"duration_seconds": 1.5}, {"hardware_enabled": "yes"},
    {"event_id": "TOO-LONG-ID"}, {"rotation": 90}, {"unexpected": 1},
])
def test_validation_rejects_nonfinite_and_unexpected_types(engine, patch):
    with pytest.raises(ValueError):
        engine.update(patch)


def test_zero_request_prevents_activation(engine):
    engine.update({"requested_kw": 0})
    with pytest.raises(ValueError):
        engine.action("start")


def test_persistence_restart_is_ready(tmp_path, clock):
    path = tmp_path / "settings.json"
    engine = Engine(path, clock)
    engine.update({"baseline_kw": 7.1, "preview_palette": "white"})
    engine.action("start")
    rebooted = Engine(path, clock)
    assert rebooted.settings.baseline_kw == 7.1
    assert rebooted.snapshot()["mode"] == "ready"


def test_failed_save_does_not_change_live_settings(tmp_path, clock):
    engine = Engine(clock=clock)
    engine.path = Path(tmp_path)  # target is a directory; replace must fail
    with pytest.raises(OSError):
        engine.update({"requested_kw": 9.0})
    assert engine.settings.requested_kw == 2.0
