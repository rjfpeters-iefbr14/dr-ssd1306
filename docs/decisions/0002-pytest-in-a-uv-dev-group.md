# 0002. pytest in a uv dev dependency group; hatchling builds

- Status: Accepted
- Date: 2026-10-25

## Context

The skeleton ran its tests with `unittest` against a real `ThreadingHTTPServer` and built
with `uv_build`. dr-st7789v uses pytest, FastAPI's `TestClient` and hatchling.

## Decision

- pytest and httpx are in a `[dependency-groups] dev` group, which plain `uv sync`
  installs; `uv run pytest` runs the tests.
- The tests are pytest functions, one file per module: `test_model`, `test_render`,
  `test_display`, `test_web`, `test_logs`, `test_display_ssd1306_plugin`. They keep the
  skeleton's fake clock and fake display.
- hatchling builds the wheel and sdist.

## Consequences

- `uv sync` gives a working test setup with no flags.
- The test that connects the FSP's plugin host runs only where `acsi_plugins` is
  installed; it is skipped otherwise.
