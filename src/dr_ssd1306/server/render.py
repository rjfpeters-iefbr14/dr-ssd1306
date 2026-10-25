"""Exact 128×64 one-bit renderer; preview color is a separate physical overlay."""

import json
from pathlib import Path

from PIL import Image, ImageDraw

GLYPHS = json.loads(Path(__file__).with_name("glyphs.json").read_text())


def text(draw, value, x, y, scale=1):
    for i, char in enumerate(str(value).upper()):
        for j, row in enumerate(GLYPHS.get(char, GLYPHS["-"])):
            for k, pixel in enumerate(row):
                if pixel == "1":
                    left, top = x + i * 6 * scale + k * scale, y + j * scale
                    draw.rectangle((left, top, left + scale - 1, top + scale - 1), fill=1)


def mmss(seconds):
    seconds = min(5999, max(0, int(seconds)))
    return f"{seconds // 60:02}:{seconds % 60:02}"


def render(state):
    image = Image.new("1", (128, 64))
    draw = ImageDraw.Draw(image)
    config = state["settings"]
    mode = state["display_state"]
    labels = {"ready": "READY", "scheduled": "ARMED", "active": "ACTIVE", "done": "DONE", "lost": "NO LINK"}
    text(draw, config["event_id"], 2, 1)
    text(draw, labels[mode], 49, 1)
    draw.line((0, 10, 127, 10), fill=1)
    if mode == "lost":
        draw.line((115, 1, 122, 7), fill=1)
        draw.line((122, 1, 115, 7), fill=1)
    else:
        for i, height in enumerate((3, 5, 7)):
            draw.rectangle((112 + i * 5, 8 - height, 114 + i * 5, 7), fill=1)
    kw = config["requested_kw"] if mode in ("ready", "scheduled") else state["delivered_kw"]
    text(draw, f"{kw:.1f}", 2, 17, scale=2)
    text(draw, {"ready": "AVAIL", "scheduled": "REQ", "active": "REDUCE", "done": "AVG", "lost": "STALE"}[mode], 54, 16)
    text(draw, "KW", 54, 25)
    draw.line((94, 16, 94, 30, 127, 30), fill=1)
    history = state["history_kw"][-32:]
    if mode == "lost":
        text(draw, "-", 109, 22)
    else:
        ceiling = max(config["baseline_kw"], config["demand_kw"], max(history, default=1), 0.1)
        points = [(95 + round(i * 31 / max(1, len(history) - 1)), 29 - round(value / ceiling * 12)) for i, value in enumerate(history)]
        if len(points) > 1:
            draw.line(points, fill=1)
    detail = f"LOAD {config['baseline_kw']:.1f} KW" if mode == "ready" else f"REQ {config['requested_kw']:.1f} KW"
    if mode == "lost":
        detail = "AGE " + mmss(state["stale_seconds"])
    text(draw, detail, 2, 34)
    if mode == "lost":
        text(draw, "CHECK LINK", 2, 44)
    else:
        pct = state["fulfilment_percent"] if mode in ("active", "done") else 0
        filled = round(min(100, max(0, pct)) / 100 * 15)
        for i in range(15):
            if i < filled:
                draw.rectangle((2 + i * 6, 45, 5 + i * 6, 50), fill=1)
            else:
                draw.point((2 + i * 6, 45), fill=1)
                draw.point((5 + i * 6, 50), fill=1)
        text(draw, str(min(999, pct)) + "%", 101, 44)
    footer = {
        "ready": "WAIT FOR REQUEST",
        "scheduled": "IN " + mmss(state["starts_in_seconds"]),
        "active": "LEFT " + mmss(state["remaining_seconds"]),
        "done": "EVENT COMPLETE",
        "lost": "DATA STALE",
    }[mode]
    text(draw, footer, 2, 56)
    return image


def colorize(image, palette="yellow-blue", rotation=0):
    # The SSD1306 receives only the one-bit image. Color depends on the panel.
    image = image.convert("1")
    if rotation == 180:
        image = image.transpose(Image.Transpose.ROTATE_180)
    result = Image.new("RGB", image.size)
    for y in range(64):
        rgb = (255, 216, 48) if palette == "yellow-blue" and y < 16 else (40, 185, 255)
        if palette == "white":
            rgb = (255, 255, 255)
        for x in range(128):
            if image.getpixel((x, y)):
                result.putpixel((x, y), rgb)
    return result
