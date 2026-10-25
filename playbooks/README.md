# Playbooks

Playbooks for the [iec61850-websocket](https://github.com/netbeheer-nederland/iec61850-websocket) rti-demo, in
its playbook format (the rti-demo's `examples/rti-demo/playbooks/README.md` has the full step reference). They
run through the rti-demo's BFF, so its HMI **Traffic** page shows each step as it happens, and the OLED shows
what the SO asks for.

| Playbook | | Participant |
|---|---|---|
| [`dr-event.yaml`](dr-event.yaml) | The SO starts, changes and ends a DR event on the OLED through SP01; the power and applied limit come back in SP01's reports | - |
| [`dr-link-loss.yaml`](dr-link-loss.yaml) | SP01 drops off for 10 s during an event: the OLED shows NO LINK, then the values are written again | - |

The OLED has no Accept or Override: an event runs as soon as the SO asks for it (decision
[0003](../docs/decisions/0003-plugin-api-version-2.md)).

## Before running

1. The display service runs and SP01 reaches it (`uv run dr-ssd1306 serve --host 0.0.0.0`, or
   `docker compose up -d` here).
2. SP01 (model_1, cp1: the model with `LD0/DWMX1.WMaxSpt`) has the plugin in its plugin configuration, for
   example the iec61850-websocket-demo stack's `modules/fsp01/plugins.json`:

   ```json
   {"name": "display_ssd1306", "url": "http://<display>:8080/plugin", "settings": {}}
   ```

   `display_ssd1306` and dr-st7789v's `display_st7789` both claim `LD0/DWMX1.WMaxSpt.Oper.ctlVal`, so one FSP
   has one of them. To run both displays, give each its own FSP with model_1, and change `SP01` in the
   playbooks to the other FSP's name.
3. The rti-demo stack is up and the SO and the FSP are registered with the BFF as SO and SP01 (HMI → Connections).

## Running

From the rti-demo, which has the runner:

```bash
cd ../iec61850-websocket/examples/rti-demo
uv run python -m playbooks.run /path/to/dr-ssd1306/playbooks/dr-event.yaml
uv run python -m playbooks.run /path/to/dr-ssd1306/playbooks/dr-event.yaml --pace 0 --steps 9-12
```

Or upload it in the HMI: Traffic → Playbook → Upload, then Run. Each playbook starts from a known state
(reporting off, no event) and ends with the event ended, so they run in any order.

The playbooks assume the OLED's default settings: a 5.0 kW baseline and a 3.2 kW simulated demand. A limit below
the baseline starts an event, and 6000 W ends it. With other settings, change the values.
