# 0001. The layout and setup of dr-st7789v: server and plugin subpackages, Docker files in docker/

- Status: Accepted
- Date: 2026-10-25

## Context

The project started as a self-contained skeleton, `dr_oled_demo`: one flat package with
the HTTP server, the engine, the renderer and the I²C writer, a root `Dockerfile` and
`compose.yaml`. It becomes an RTI-FSP plugin next to dr-st7789v, the ST7789 display, which
has the same purpose; one layout for both makes them easier to run and change together.

## Decision

- The package is `dr_ssd1306` (distribution and command `dr-ssd1306`, plugin name
  `display_ssd1306`), version 0.2.0.
- The display service is the subpackage `dr_ssd1306.server` (`cli`, `web`, `model`,
  `render`, `display`, `logs`, `glyphs.json`, `static/`). The console script is
  `dr_ssd1306.server.cli:main`, with the commands `serve` and `render`.
- The plugin is the subpackage `dr_ssd1306.plugin` (`mapping`, `plugin`).
- The Dockerfile is `docker/Dockerfile`, with `docker/Dockerfile.dockerignore`; the build
  context is the repository root. `docker-compose.yaml` runs the simulation,
  `docker-compose.pi.yaml` adds the OLED on I²C.
- Decisions in `docs/decisions/`, design assets in `docs/design/`, rti-demo playbooks in
  `playbooks/`.
- The port stays 8080, so the OLED and the ST7789 display (8000) can run on one Pi.

## Consequences

- `dr-oled-demo --simulate` becomes `dr-ssd1306 serve --simulate`; `--debug` becomes
  `--log-level debug`. The settings file moves to `~/.config/dr-ssd1306/settings.json`,
  the password variable from `DR_OLED_PASSWORD` to `DR_SSD1306_PASSWORD`.
- The `hardware` extra is now `pi`, as in dr-st7789v.
