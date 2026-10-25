# 0003. The plugin is the rti-demo's plugin API, version 2, on the OLED's own engine

- Status: Proposed
- Date: 2026-10-25

## Context

iec61850-websocket's FSP connects to a plugin as an HTTP service that implements the plugin
API of its `openapi.yaml`, contract version 2 (its decision 0029). dr-st7789v serves one at
`/plugin` (its decision 0008) with its own DR model: a simulator with Accept and Override.
The OLED has a different engine: a requested reduction, a simulated demand, scheduled and
timed events, a time-weighted average and a simulated DR link. That engine is kept.

## Decision

- `dr_ssd1306.plugin` implements the plugin API under `/plugin`, in the display service, as
  dr-st7789v does: `GET /plugin` (name `display_ssd1306`, `api` 2, the claim
  `LD0/DWMX1.WMaxSpt.Oper.ctlVal`, `routes` `/api`), `POST /plugin/start`, `/stop`,
  `/events`, `/control`, `GET /plugin/attached`, and `/plugin/status`, `/plugin/resync`.
- The SO's limit maps onto the engine:
  - an Operate on `LD0/DWMX1.WMaxSpt` below the baseline sets `requested_kw` to the
    baseline minus the limit (0.1 kW) and runs `start`; a new limit starts the event again;
  - a limit at or above the baseline ends it: `complete` when active, `ready` when
    scheduled;
  - `Associated` runs `link-restored`, `ServerStopped` `link-lost`.
- It writes into the FSP's model, through `POST /api/writevalue`: the power
  (`LD0/MMXU1.TotW.mag.f`, the demand during an event, else the baseline) and the applied
  limit (`LD0/DWMX1.WMaxSpt.mxVal.f`, the baseline minus the request during an event, else
  the baseline).
- One FSP at a time, the most recent one that started it; after a restart of the service,
  the first FSP that sends an event or an Operate is served with the default settings.

## Consequences

- The demand stays what the operator sets in the web controls; nothing ramps it, and there
  is no participant decision: the event runs as soon as the SO asks.
- The requested reduction the SO sets is saved in the settings file, like a change in the
  web controls.
- An Operate the engine refuses (a lost DR link, an invalid value) is answered by the FSP
  already; the plugin logs it and shows it in `last_error`.
