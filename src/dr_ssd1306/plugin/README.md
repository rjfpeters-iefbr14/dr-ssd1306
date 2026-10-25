# display-ssd1306-plugin

An RTI-FSP plugin (plugin name `display_ssd1306`) for the
[iec61850-websocket](https://github.com/netbeheer-nederland/iec61850-websocket) rti-demo. Connected to an FSP,
it shows the SO's demand-response requests on the dr-ssd1306 OLED. The simulated power and the limit the site
applies then go back to the SO in the FSP's reports.

It implements the rti-demo's **plugin API, contract version 2** (`openapi.yaml` in the rti-demo's
`modules/plugins`, tag *Plugin API*): an HTTP service under `/plugin` of the dr-ssd1306 service, which the FSP
connects to from its plugin configuration (decision [0003](../../../docs/decisions/0003-plugin-api-version-2.md)).
Nothing of it is installed in the FSP. It runs in the display service and acts on its engine directly.

| Call | What the display does |
|---|---|
| `GET /plugin` | `{"name": "display_ssd1306", "api": 2, "claims": ["LD0/DWMX1.WMaxSpt.Oper.ctlVal"], "routes": "/api"}` |
| `POST /plugin/start` | From an FSP: writes the display's values to its `host_url` from now on, every `poll_seconds`. From an SO: nothing |
| `POST /plugin/events` | Shows the FSP's events on the display (below) |
| `POST /plugin/control` | Remembers the power limit of an Operate; answers `204`, so the FSP's own check decides |
| `POST /plugin/stop` | Stops writing to that FSP |
| `GET /plugin/attached` | The OLED, for the HMI box next to the FSP (rti-demo decision 0025): `ok`, `degraded` while writes or the OLED fail, `down` while the DR link is lost; power, applied limit and, during an event, the delivered reduction in kW |

## What it does

| On the ACSI side | On the OLED's engine |
|---|---|
| The SO operates `LD0/DWMX1.WMaxSpt` (power limit, W) below the baseline | `requested_kw` = baseline − limit / 1000 (0.1 kW), then **start**: the event runs for `duration_seconds`. A new limit starts it again |
| The SO operates `LD0/DWMX1.WMaxSpt` at or above the baseline | The event ends: **complete** when active, **ready** when scheduled |
| Association set up (`Associated`) / FSP server stopped (`ServerStopped`) | **link-restored** / **link-lost**: the OLED shows NO LINK with the last values, stale |

| On the OLED | Written into the FSP's model (every `poll_seconds`) | Reaches the SO in |
|---|---|---|
| The power: `demand_kw` during an event, else `baseline_kw`, × 1000 (changes ≥ `min_change_w`) | `LD0/MMXU1.TotW.mag.f` | `ActualValues` report |
| The limit applied: `baseline_kw` − `requested_kw` during an event, else `baseline_kw` | `LD0/DWMX1.WMaxSpt.mxVal.f` | `Setpoints` report |

There is no participant decision: the event runs as soon as the SO asks, and the simulated demand stays what the
web controls set. The requested reduction is saved in the settings file, like a change in the web controls. An
Operate the engine refuses, for example while the DR link is lost, is logged and shows as `last_error` in
`/plugin/status`.

The plugin claims `LD0/DWMX1.WMaxSpt.Oper.ctlVal`, so no other plugin may claim it in the same FSP (dr-st7789v's
`display_st7789` does too). Values are written through the FSP's own `POST /api/writevalue`, which needs the FSP's
server to be started. Until then, `last_error` shows the error and the next poll tries again.

It serves one FSP at a time: the most recent one that started it. The events and Operates of another FSP are
left alone.

The FSP calls `/start` only when it starts, or when the plugin is added, edited or reloaded. After a restart of the
display service, the first FSP that sends an event or an Operate is served again, with the default settings. For
other settings, reload the plugin in the FSP (`POST /api/plugins/display_ssd1306/reload`).

## Settings

From the plugin configuration, sent with `/start`. Unknown settings are refused (`422`).

| Setting | Default | |
|---|---|---|
| `poll_seconds` | `1` | How often the display's values are written |
| `w_per_kw` | `1000` | The model is in W, the display in kW |
| `min_change_w` | `50` | Smaller power changes aren't written |
| `power_ref`, `applied_limit_ref` | see above | Where to write; `""` turns a write off |

Routes: through the FSP, `/api/plugins/display_ssd1306/*` is the display's `/api/*` (for example `GET
/api/plugins/display_ssd1306/state`), when no password is set. On the display only: `GET /plugin/status` (the FSP
it writes to, the last request and writes) and `POST /plugin/resync` (write all values again). With
`DR_SSD1306_PASSWORD` set, the plugin API needs no password: the FSP can't sign in.

## Connect an FSP to it

On the Raspberry Pi that has the OLED, start the display service so the FSP can reach it:

```bash
uv run --extra pi dr-ssd1306 serve --hardware --host 0.0.0.0 --port 8080   # or --simulate
```

Add the plugin to the FSP's plugin configuration (an FSP with model_1, which has `LD0/DWMX1.WMaxSpt`):

```json
{
  "host_url": "http://<fsp-address>:5001",
  "plugins": [
    {"name": "display_ssd1306", "url": "http://<pi-address>:8080/plugin", "settings": {}}
  ]
}
```

`host_url` is where the display reaches the FSP: an address of the FSP's host that the Pi can reach.
