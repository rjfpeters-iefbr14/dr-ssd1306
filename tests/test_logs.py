import logging

import pytest
from fastapi.testclient import TestClient

from dr_ssd1306.server import cli
from dr_ssd1306.server.logs import QuietPollFilter, resolve_log_level
from dr_ssd1306.server.model import Engine
from dr_ssd1306.server.web import create_app


@pytest.mark.parametrize("value, level", [
    (None, logging.INFO),
    ("", logging.INFO),
    ("debug", logging.DEBUG),
    (" Warning ", logging.WARNING),
    ("trace", logging.DEBUG),
    ("10", 10),
    ("loud", logging.INFO),
])
def test_resolve_log_level(value, level):
    assert resolve_log_level(value) == level


def access(method, path, status=200):
    """A uvicorn access record: (client_addr, method, path, http_version, status)."""
    return logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 0, '%s - "%s %s HTTP/%s" %d',
        ("192.168.0.231:4000", method, path, "1.1", status), None,
    )


@pytest.fixture
def access_logger():
    logger = logging.getLogger("uvicorn.access")
    level = logger.level
    yield logger
    logger.setLevel(level)


@pytest.mark.parametrize("method, path", [
    ("GET", "/health"),
    ("GET", "/api/state"),
    ("GET", "/api/screen.png?t=1792839271"),
    ("GET", "/plugin/attached"),
    ("GET", "/plugin/status"),
])
def test_polls_are_demoted_to_debug(access_logger, method, path):
    access_logger.setLevel(logging.INFO)
    record = access(method, path)
    assert QuietPollFilter().filter(record) is False
    assert (record.levelno, record.levelname) == (logging.DEBUG, "DEBUG")
    access_logger.setLevel(logging.DEBUG)
    assert QuietPollFilter().filter(access(method, path)) is True


@pytest.mark.parametrize("method, path", [
    ("POST", "/api/settings"),  # an operator's change
    ("POST", "/api/action"),
    ("POST", "/plugin/events"),
    ("POST", "/plugin/control"),
    ("POST", "/plugin/start"),
    ("GET", "/"),
])
def test_other_requests_stay_at_info(access_logger, method, path):
    access_logger.setLevel(logging.INFO)
    record = access(method, path)
    assert QuietPollFilter().filter(record) is True
    assert record.levelno == logging.INFO


def test_a_record_that_isn_t_an_access_line_passes():
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 0, "plain", None, None)
    assert QuietPollFilter().filter(record) is True


def test_the_app_installs_the_filter_once(access_logger):
    for _ in range(2):
        with TestClient(create_app(Engine())):
            pass
    assert sum(isinstance(f, QuietPollFilter) for f in access_logger.filters) == 1


def test_serve_logs_through_the_root_logger_at_the_chosen_level(monkeypatch, tmp_path):
    calls = {}
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kwargs: calls.update(kwargs))
    monkeypatch.setenv("LOG_LEVEL", "warning")
    root = logging.getLogger()
    level, handlers = root.level, root.handlers[:]
    try:
        config = str(tmp_path / "settings.json")
        cli.main(["serve", "--config", config, "--log-level", "debug"])
        assert root.level == logging.DEBUG
        assert (calls["log_level"], calls["log_config"]) == ("debug", None)
        cli.main(["serve", "--config", config])
        assert root.level == logging.WARNING
        assert calls["log_level"] == "warning"
    finally:
        root.setLevel(level)
        root.handlers[:] = handlers
