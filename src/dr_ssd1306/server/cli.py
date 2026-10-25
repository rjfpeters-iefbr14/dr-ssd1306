"""Console commands: serve (engine + web + OLED) and render (still screenshot)."""

import argparse
import logging
import os
from pathlib import Path

import uvicorn

from .logs import LOG_CHOICES, configure_logging, resolve_log_level, uvicorn_log_level
from .model import Engine
from .render import colorize, render

DEFAULT_CONFIG = Path("~/.config/dr-ssd1306/settings.json")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="dr-ssd1306", description="Web-controlled 128x64 SSD1306 demand-response demo")
    sub = parser.add_subparsers(dest="command", required=True)

    server = sub.add_parser("serve", help="Serve the web controls, optionally drive the I2C OLED")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8080)
    server.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="settings file (default %(default)s)")
    output = server.add_mutually_exclusive_group()
    output.add_argument("--hardware", action="store_true", help="enable the saved I2C display settings at startup")
    output.add_argument("--simulate", action="store_true", help="disable the physical display at startup")
    server.add_argument("--log-level", default=None,
                        help=f"{', '.join(LOG_CHOICES)} (default: LOG_LEVEL, else info); polls show at debug")

    still = sub.add_parser("render", help="Save a 128x64 PNG of the current settings")
    still.add_argument("--config", type=Path, default=None, help="settings file (default: the built-in settings)")
    still.add_argument("--action", choices=["ready", "schedule", "start", "complete", "link-lost"], default="start")
    still.add_argument("--raw", action="store_true", help="the one-bit frame the driver gets, not the colour preview")
    still.add_argument("--output", type=Path, default=Path("screen.png"))

    args = parser.parse_args(argv)
    if args.command == "render":
        engine = Engine(args.config.expanduser() if args.config else None)
        engine.path = None  # a still never changes the settings file
        state = engine.action(args.action)
        image = render(state)
        if not args.raw:
            image = colorize(image, state["settings"]["preview_palette"], state["settings"]["rotation"])
        args.output.parent.mkdir(parents=True, exist_ok=True)
        image.save(args.output)
        print(f"Saved {args.output} (128x64)")
        return

    # --log-level wins over LOG_LEVEL; uvicorn's loggers follow the same level.
    log_level = args.log_level or os.getenv("LOG_LEVEL", "info")
    level = resolve_log_level(log_level)
    configure_logging(level)
    log = logging.getLogger(__name__)
    try:
        engine = Engine(args.config.expanduser())
        if args.hardware or args.simulate:
            engine.update({"hardware_enabled": args.hardware})
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Startup failed: {exc}\n")
    from .display import DisplayWorker
    from .web import create_app
    app = create_app(engine, password=os.environ.get("DR_SSD1306_PASSWORD") or None, worker=DisplayWorker(engine))
    log.info("Serving on %s:%d (log level %s; all demand-response data is simulated)",
             args.host, args.port, logging.getLevelName(level))
    # log_config=None: uvicorn's records go to the root logger, in its format.
    uvicorn.run(app, host=args.host, port=args.port,
                log_level=uvicorn_log_level(log_level, level), log_config=None)


if __name__ == "__main__":
    main()
