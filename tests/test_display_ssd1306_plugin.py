"""The display_ssd1306 plugin API (contract version 2) on the real display app, with a fake FSP.

The FSP's side, the plugin host acsi_plugins, lives in iec61850-websocket; the last test
connects it when it is installed, and is skipped otherwise.
"""

import pytest
from fastapi.testclient import TestClient

from dr_ssd1306.plugin.mapping import OPERATE_REF, Settings, ctl_number, requested_reduction_kw
from dr_ssd1306.server.model import Engine
from dr_ssd1306.server.web import create_app

FSP = {"name": "display_ssd1306", "role": "fsp", "host_url": "http://fsp:5001"}
OTHER_FSP = {"name": "display_ssd1306", "role": "fsp", "host_url": "http://fsp02:5005"}
SO = {"name": "display_ssd1306", "role": "so", "host_url": "http://so:5000"}
SETTINGS = {"poll_seconds": 3600}


class Rig:
    """The display app with its plugin, started by a fake FSP that records the writes."""

    def __init__(self, client: TestClient, engine: Engine):
        self.client = client
        self.engine = engine
        self.plugin = client.app.state.plugin
        self.fsp_writes = []
        self.fsp_up = True
        self.plugin._http = self.http

    def http(self, method, url, body=None):
        if not self.fsp_up:
            raise ConnectionError("fsp down")
        assert (method, url) == ("POST", "http://fsp:5001/api/writevalue")
        self.fsp_writes.append(body)
        return {"ok": True}

    def start(self, host=FSP, settings=SETTINGS):
        return self.client.post("/plugin/start", json={**host, "settings": settings})

    def poll(self):
        self.client.portal.call(self.plugin.poll_once)

    def values(self):
        self.poll()
        return [(w["objRef"], w["value"]) for w in self.fsp_writes]

    def event(self, event, host=FSP):
        response = self.client.post("/plugin/events", json={"host": host, "event": event})
        assert response.status_code == 200, response.text

    def operate(self, limit_w, success=True, host=FSP):
        ctl_val = {"type": "float32", "value": ["float32", limit_w]}
        answer = self.client.post("/plugin/control", json={"host": host, "obj_ref": OPERATE_REF, "ctl_val": ctl_val})
        self.event({"type": "OperateResponse", "success": success}, host)
        return answer


@pytest.fixture
def engine(clock):
    return Engine(clock=clock)  # baseline 5.0 kW, demand 3.2 kW, no settings file


@pytest.fixture
def rig(engine):
    with TestClient(create_app(engine)) as client:
        rig = Rig(client, engine)
        assert rig.start().status_code == 200
        rig.poll()
        yield rig


@pytest.fixture
def restarted(engine):
    """The display app after a restart: its FSP still runs, but hasn't started it again."""
    with TestClient(create_app(engine)) as client:
        yield Rig(client, engine)


# ---------- the mapping ----------


def test_ctl_number_unwraps_every_shape():
    assert ctl_number({"type": "float32", "value": ["float32", 1500.0]}) == 1500.0
    assert ctl_number({"value": {"mag": {"f": "2000"}}}) == 2000.0
    assert ctl_number(750) == 750.0
    assert ctl_number({"value": ["boolean", True]}) is None
    assert ctl_number({"value": "nan"}) is None


def test_the_request_is_the_baseline_minus_the_limit():
    state = {"settings": {"baseline_kw": 5.0}}
    assert requested_reduction_kw(3000, state, Settings()) == 2.0
    assert requested_reduction_kw(4970, state, Settings()) == 0.0  # rounds to nothing: no event
    assert requested_reduction_kw(6000, state, Settings()) == 0.0
    assert requested_reduction_kw(-5, state, Settings()) == 5.0


@pytest.mark.parametrize("name", ["event_minutes", "display_url"])
def test_unknown_setting_is_refused(name):
    with pytest.raises(ValueError, match=f"Unknown settings: {name}"):
        Settings.from_settings({name: 1})


# ---------- the plugin API ----------


def test_it_describes_itself():
    body = TestClient(create_app(Engine())).get("/plugin").json()
    assert (body["name"], body["api"], body["claims"], body["routes"]) == ("display_ssd1306", 2, [OPERATE_REF], "/api")


def test_start_needs_the_fsp_s_url_and_known_settings(rig):
    assert rig.start({**FSP, "host_url": None}).status_code == 422
    assert rig.start(settings={"event_minutes": 30}).status_code == 422


def test_an_so_leaves_it_idle(rig):
    assert rig.start(SO).status_code == 200
    assert rig.plugin.host.host_url == "http://fsp:5001"


def test_power_and_applied_limit_are_written_to_the_fsp(rig):
    assert rig.fsp_writes == [
        {"objRef": "LD0/MMXU1.TotW.mag.f", "fc": "mx", "value": "5000.0", "dataType": "float32"},
        {"objRef": "LD0/DWMX1.WMaxSpt.mxVal.f", "fc": "mx", "value": "5000.0", "dataType": "float32"},
    ]
    rig.fsp_writes.clear()
    rig.operate(3000.0)
    assert rig.values() == [("LD0/MMXU1.TotW.mag.f", "3200.0"), ("LD0/DWMX1.WMaxSpt.mxVal.f", "3000.0")]
    rig.fsp_writes.clear()
    rig.engine.update({"demand_kw": 3.22})  # rounds to 3.2: no change
    assert rig.values() == []


def test_a_limit_below_the_baseline_starts_the_event(rig):
    assert rig.operate(3000.0).status_code == 204  # left to the FSP's own type check
    state = rig.engine.snapshot()
    assert (state["mode"], state["settings"]["requested_kw"]) == ("active", 2.0)
    assert rig.plugin.last_request["action"] == "start"


def test_a_new_limit_starts_it_again(rig, clock):
    rig.operate(3000.0)
    clock.advance(60)
    rig.operate(1500.0)
    state = rig.engine.snapshot()
    assert (state["mode"], state["settings"]["requested_kw"]) == ("active", 3.5)
    assert state["remaining_seconds"] == state["settings"]["duration_seconds"]


def test_a_limit_at_the_baseline_ends_it(rig):
    rig.operate(3000.0)
    rig.operate(5000.0)
    assert rig.engine.snapshot()["mode"] == "done"
    rig.engine.action("schedule")
    rig.operate(6000.0)
    assert rig.engine.snapshot()["mode"] == "ready"
    rig.operate(6000.0)  # nothing runs: nothing to end
    assert rig.engine.snapshot()["mode"] == "ready"


def test_a_failed_operate_changes_nothing(rig):
    rig.operate(3000.0, success=False)
    assert rig.engine.snapshot()["mode"] == "ready"


def test_a_limit_the_engine_refuses_is_logged(rig):
    rig.event({"type": "ServerStopped"})  # the DR link is lost: the engine won't start
    rig.operate(3000.0)
    assert rig.engine.snapshot()["mode"] == "ready"
    assert "Restore the demo link" in rig.plugin.last_error


def test_association_and_stop_restore_and_lose_the_link(rig):
    rig.event({"type": "ServerStopped"})
    assert rig.engine.snapshot()["display_state"] == "lost"
    rig.event({"type": "Associated", "associate_id": "a1"})
    assert rig.engine.snapshot()["link_ok"] is True
    rig.event({"type": "SomethingNew"})


def test_another_fsp_is_left_alone(rig):
    rig.operate(3000.0, host=OTHER_FSP)
    rig.event({"type": "ServerStopped"}, OTHER_FSP)
    state = rig.engine.snapshot()
    assert (state["mode"], state["link_ok"]) == ("ready", True)


def test_a_write_that_fails_is_tried_again(rig):
    rig.fsp_up = False
    rig.client.post("/plugin/resync")
    rig.poll()
    assert "fsp down" in rig.plugin.last_error
    rig.fsp_up = True
    rig.fsp_writes.clear()
    rig.poll()
    assert len(rig.fsp_writes) == 2
    assert rig.plugin.last_error is None


def test_stop_ends_the_writes(rig):
    rig.client.post("/plugin/stop", json=FSP)
    assert rig.plugin.host is None
    rig.fsp_writes.clear()
    rig.client.post("/plugin/resync")
    rig.poll()
    assert rig.fsp_writes == []


def test_status_route(rig):
    body = rig.client.get("/plugin/status").json()
    assert body["host"]["host_url"] == "http://fsp:5001"
    assert body["operate_ref"] == OPERATE_REF
    assert body["writes"] == 2


# ---------- attached (rti-demo decision 0025) ----------


def test_attached_shows_the_oled_with_its_power_and_event(rig):
    rig.operate(3000.0)
    [item] = rig.client.get("/plugin/attached").json()["items"]
    assert (item["kind"], item["label"], item["state"]) == ("display", "SSD1306 OLED", "ok")
    assert item["address"] == "http://testserver"
    assert item["detail"] == "DR event, 90% of the request"
    assert item["live"] == [{"type": "values", "items": [
        {"label": "Power", "value": 3.2, "unit": "kW"},
        {"label": "Applied limit", "value": 3.0, "unit": "kW"},
        {"label": "Reduction", "value": 1.8, "unit": "kW"},
    ]}]


def test_attached_shows_failures_and_a_lost_link(rig):
    rig.engine.set_hardware("error", "OSError: I2C remote I/O error")
    item = rig.client.get("/plugin/attached").json()["items"][0]
    assert (item["state"], item["detail"]) == ("degraded", "OSError: I2C remote I/O error")
    rig.event({"type": "ServerStopped"})
    assert rig.client.get("/plugin/attached").json()["items"][0]["state"] == "down"


def test_attached_without_an_event_has_no_reduction(rig):
    item = rig.client.get("/plugin/attached").json()["items"][0]
    assert item["detail"] == "ready"
    assert [v["label"] for v in item["live"][0]["items"]] == ["Power", "Applied limit"]


# ---------- after a restart of the display service ----------


def test_after_a_restart_the_first_fsp_event_starts_it_with_default_settings(restarted):
    assert restarted.plugin.host is None
    restarted.event({"type": "Associated", "associate_id": "a1"})
    assert restarted.plugin.host.host_url == "http://fsp:5001"
    assert restarted.plugin.settings == Settings()
    restarted.poll()
    assert len(restarted.fsp_writes) == 2


def test_after_a_restart_an_operate_starts_it_and_the_event(restarted):
    restarted.operate(3000.0)
    assert restarted.plugin.host.host_url == "http://fsp:5001"
    assert restarted.engine.snapshot()["mode"] == "active"


def test_after_a_restart_an_so_or_a_stopped_fsp_doesn_t_start_it(restarted):
    restarted.event({"type": "Associated", "associate_id": "a1"}, SO)
    restarted.event({"type": "ServerStopped"})
    assert restarted.plugin.host is None


def test_an_fsp_connects_to_it_through_its_plugin_configuration():
    acsi_plugins = pytest.importorskip("acsi_plugins")
    from acsi_plugins.web import PluginService, attach
    from fastapi import FastAPI
    import httpx2 as httpx

    display = create_app(Engine())

    def client():
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=display), base_url="http://display:8080")

    host = acsi_plugins.PluginHost(role="fsp", host_url="http://fsp:5001")
    service = PluginService(
        host, configured=[acsi_plugins.PluginEntry("display_ssd1306", "http://display:8080/plugin", SETTINGS)],
        client_factory=client, retry_seconds=0,
    )
    app = FastAPI(lifespan=service.lifespan)
    attach(app, service)
    with TestClient(app) as fsp:
        [status] = fsp.get("/api/plugins").json()["plugins"]
        assert (status["name"], status["claims"]) == ("display_ssd1306", [OPERATE_REF])
        # Its routes are the display's /api.
        assert fsp.get("/api/plugins/display_ssd1306/state").json()["mode"] == "ready"
