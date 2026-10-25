# 0005. Logging like the rti-demo's FSP: LOG_LEVEL, one format, polls at DEBUG

- Status: Accepted
- Date: 2026-10-25

## Context

The browser page polls `/api/state` and `/api/screen.png` every second, the FSP asks
`/plugin/attached` about every 2 s and Docker checks `/health`; at INFO they bury the
requests that change something. The rti-demo's FSP and dr-st7789v solve this the same way.

## Decision

- `serve` logs to stdout through the root logger, in the FSP's format, at `LOG_LEVEL` or
  `--log-level` (which wins); an unknown level gives info. uvicorn runs with
  `log_config=None`, so its lines use the same format.
- `QuietPollFilter` on `uvicorn.access` demotes those polls, by method and path, to DEBUG.

## Consequences

- At info, a `POST /api/settings`, an action or a plugin call shows; the polls show at
  debug.
