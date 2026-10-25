# Implementation decisions

One file per decision, numbered in the order the decisions were made:
`NNNN-short-title.md`. Copy [`template.md`](template.md) to add one.

A decision is never edited to say something different. When it changes, add a new
record and set the old one's status to `Superseded by NNNN`.

| # | Decision | Status |
|---|---|---|
| [0001](0001-same-layout-as-dr-st7789v.md) | The layout and setup of dr-st7789v: server and plugin subpackages, Docker files in `docker/` | Accepted |
| [0002](0002-pytest-in-a-uv-dev-group.md) | pytest in a uv dev dependency group; hatchling builds | Accepted |
| [0003](0003-plugin-api-version-2.md) | The plugin is the rti-demo's plugin API, version 2, on the OLED's own engine | Proposed |
| [0004](0004-fastapi-web-service.md) | FastAPI instead of `http.server`; the plugin API and `/health` need no password | Accepted |
| [0005](0005-logging-like-the-fsp.md) | Logging like the rti-demo's FSP: `LOG_LEVEL`, one format, polls at DEBUG | Accepted |
