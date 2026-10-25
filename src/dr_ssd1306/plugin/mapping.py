"""Translation between the FSP's IEC 61850 model and the OLED engine's DR state.

Pure functions, no I/O: the plugin calls them, the tests call them directly.
"""

from dataclasses import dataclass, fields
import math

# The Operate the SO sends to start, change or end a DR event: the maximum
# power setpoint of the FSP's DER (model_1, APC, float32, W). Fixed here,
# because the FSP reads the claims from the description, before /start
# gives the settings.
OPERATE_REF = "LD0/DWMX1.WMaxSpt.Oper.ctlVal"


@dataclass
class Settings:
    poll_seconds: float = 1.0
    w_per_kw: float = 1000.0
    min_change_w: float = 50.0
    # Where the display's values are written in the FSP's model; "" disables one.
    power_ref: str = "LD0/MMXU1.TotW.mag.f"
    # The limit the site applies: baseline minus the request during an
    # active event, else the baseline.
    applied_limit_ref: str = "LD0/DWMX1.WMaxSpt.mxVal.f"

    @classmethod
    def from_settings(cls, settings: dict) -> "Settings":
        known = {f.name for f in fields(cls)}
        unknown = set(settings) - known
        if unknown:
            raise ValueError(f"Unknown settings: {', '.join(sorted(unknown))}")
        result = cls(**settings)
        for name in ("poll_seconds", "w_per_kw", "min_change_w"):
            value = float(getattr(result, name))
            if not math.isfinite(value) or value < 0 or (name in ("poll_seconds", "w_per_kw") and value == 0):
                raise ValueError(f"{name} must be a positive number")
            setattr(result, name, value)
        return result


def ctl_number(ctl_val) -> float | None:
    """The number in an Operate's ctlVal, however the FSP wraps it.

    The FSP passes {"type": ..., "value": ...}; the value can be a
    (type, value) pair, a {type: value} map, a {"f": ...} or
    {"mag": {"f": ...}} structure, or a plain number or string.
    """
    value = ctl_val.get("value") if isinstance(ctl_val, dict) and "value" in ctl_val else ctl_val
    for _ in range(4):
        if isinstance(value, (list, tuple)) and len(value) == 2 and isinstance(value[0], str):
            value = value[1]
        elif isinstance(value, dict) and len(value) == 1:
            value = next(iter(value.values()))
        else:
            break
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def requested_reduction_kw(limit_w: float, state: dict, settings: Settings) -> float:
    """The reduction a power limit asks for, as the engine takes it (0.1 kW).

    0 when the limit is at or above the baseline: the event ends.
    """
    baseline = state["settings"]["baseline_kw"]
    limit_kw = max(0.0, limit_w / settings.w_per_kw)
    return min(99.9, max(0.0, round(baseline - limit_kw, 1)))


def end_action(state: dict) -> str | None:
    """The engine action that ends what the SO started, if anything runs."""
    return {"active": "complete", "scheduled": "ready"}.get(state["mode"])


def power_kw(state: dict) -> float:
    """The site's simulated power: the demand during an event, else the baseline."""
    config = state["settings"]
    return float(config["demand_kw"] if state["mode"] == "active" else config["baseline_kw"])


def applied_limit_kw(state: dict) -> float:
    """The power limit the site applies, as the SO should see it."""
    config = state["settings"]
    if state["mode"] == "active":
        return round(max(0.0, config["baseline_kw"] - config["requested_kw"]), 1)
    return float(config["baseline_kw"])


def attached_item(state: dict, last_error: str | None, address: str | None) -> dict:
    """The display, for the HMI box next to the FSP (GET /plugin/attached).

    Down while the DR link is lost, degraded while writes to the FSP or the
    OLED itself fail.
    """
    hardware = state["hardware"]
    if not state["link_ok"]:
        status, detail = "down", "no link"
    elif last_error:
        status, detail = "degraded", last_error
    elif hardware["status"] == "error":
        status, detail = "degraded", hardware["error"]
    elif state["mode"] == "active":
        status, detail = "ok", f"DR event, {state['fulfilment_percent']}% of the request"
    else:
        status, detail = "ok", state["mode"]
    values = [
        {"label": "Power", "value": power_kw(state), "unit": "kW"},
        {"label": "Applied limit", "value": applied_limit_kw(state), "unit": "kW"},
    ]
    if state["mode"] == "active":
        values.append({"label": "Reduction", "value": state["delivered_kw"], "unit": "kW"})
    return {
        "kind": "display",
        "label": "SSD1306 OLED",
        "address": address,
        "state": status,
        "detail": detail,
        "live": [{"type": "values", "items": values}],
    }


def report_writes(state: dict, reported: dict, settings: Settings) -> list[dict]:
    """The FSP writes that bring its model up to the display's state.

    `reported` holds what was written last, per objRef; a power change
    smaller than min_change_w isn't written, so reports stay readable.
    """
    values = []
    if settings.power_ref:
        values.append((settings.power_ref, power_kw(state), settings.min_change_w))
    if settings.applied_limit_ref:
        values.append((settings.applied_limit_ref, applied_limit_kw(state), 0.0))
    writes = []
    for obj_ref, kw, min_change in values:
        watts = round(kw * settings.w_per_kw, 1)
        last = reported.get(obj_ref)
        if last is None or (watts != last and abs(watts - last) >= min_change):
            writes.append({"objRef": obj_ref, "fc": "mx", "value": watts, "dataType": "float32"})
    return writes


def write_body(write: dict) -> dict:
    """A write as the FSP's POST /api/writevalue takes it: the value as text."""
    value = write["value"]
    text = ("true" if value else "false") if isinstance(value, bool) else str(value)
    return {**write, "value": text}
