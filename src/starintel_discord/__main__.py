from __future__ import annotations

import logging
import os

from .bot import build_bot
from .config import ConfigError, load_config


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        config = load_config()
    except ConfigError as exc:
        raise SystemExit(f"configuration error: {exc}") from exc
    bot = build_bot(config)
    bot.run(config.discord.token, log_handler=None)


if __name__ == "__main__":
    main()
