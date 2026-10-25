import base64
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from dr_ssd1306.server.model import Engine
from dr_ssd1306.server.web import create_app

AUTH = {"Authorization": "Basic " + base64.b64encode(b"demo:test-secret").decode()}


@pytest.fixture
def engine():
    return Engine()


@pytest.fixture
def client(engine):
    with TestClient(create_app(engine, password="test-secret")) as client:
        yield client


def test_http_settings_activation_and_png(client):
    assert client.post("/api/settings", json={"demand_kw": 3.0}, headers=AUTH).json()["settings"]["demand_kw"] == 3.0
    assert client.post("/api/action", json={"action": "start"}, headers=AUTH).json()["fulfilment_percent"] == 100
    for path, mode in (("/api/screen.png", "RGB"), ("/api/screen.png?raw=1", "1")):
        image = Image.open(BytesIO(client.get(path, headers=AUTH).content))
        assert (image.size, image.mode) == ((128, 64), mode)
    assert "Save & apply" in client.get("/", headers=AUTH).text


def test_authentication_and_cross_origin_write(client):
    response = client.get("/api/state")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == 'Basic realm="DR SSD1306"'
    response = client.post("/api/action", json={"action": "start"},
                           headers={**AUTH, "Origin": "https://foreign.example"})
    assert response.status_code == 403


def test_the_healthcheck_and_the_fsp_need_no_password(client):
    assert client.get("/health").json()["ok"] is True
    assert client.get("/plugin").json()["name"] == "display_ssd1306"


def test_writes_must_be_json(client):
    response = client.post("/api/action", content=b"action=start", headers={**AUTH, "Content-Type": "text/plain"})
    assert response.status_code == 415
    response = client.post("/api/action", content=b"", headers={**AUTH, "Content-Type": "application/json"})
    assert response.status_code == 400
    response = client.post("/api/action", json={"action": "start", "extra": 1}, headers=AUTH)
    assert response.status_code == 400


def test_bad_settings_are_rejected_without_mutation(client, engine):
    response = client.post("/api/settings", json={"demand_kw": -1}, headers=AUTH)
    assert response.status_code == 400
    assert "demand_kw" in response.json()["error"]
    assert engine.settings.demand_kw == 3.2


def test_security_headers_on_every_response(client):
    for response in (client.get("/api/state"), client.get("/api/state", headers=AUTH), client.get("/health")):
        assert response.headers["X-Frame-Options"] == "DENY"
        assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


def test_without_a_password_everything_is_open(engine):
    with TestClient(create_app(engine)) as client:
        assert client.get("/api/state").json()["mode"] == "ready"
