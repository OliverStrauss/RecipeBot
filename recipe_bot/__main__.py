"""Entry point: ``python -m recipe_bot``."""

from __future__ import annotations

import logging
import shutil
import sys

if sys.version_info < (3, 11):
    sys.exit("Recipe Bot needs Python 3.11 or newer.")

import aiohttp  # installed with discord.py
import discord
from dotenv import load_dotenv

from .bot import RecipeBot
from .config import ConfigError, load_config, setup_logging
from .pipeline.download import check_ytdlp_version
from .pipeline.extract.cli_backend import CliError, check_cli

log = logging.getLogger("recipe_bot")


def startup_checks(config) -> bool:
    """Fail fast on anything that would make every job fail. Returns False to exit."""
    missing = [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]
    if missing:
        log.error("%s not found. Install ffmpeg (macOS: `brew install ffmpeg`, Pi: `sudo apt install ffmpeg`).",
                  " and ".join(missing))
        return False
    if config.claude_backend == "claude_cli":
        try:
            log.info("Claude Code CLI %s, signed in", check_cli(config.claude_cli_path))
        except CliError as exc:
            log.error("%s", exc)
            return False
    if warning := check_ytdlp_version():
        log.warning(warning)
    return True


def main() -> int:
    load_dotenv()  # reads ./.env if present; real env vars win
    try:
        config = load_config()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        print("\nSee .env.example for every setting.", file=sys.stderr)
        return 2

    setup_logging(config.log_level)
    log.info("Starting Recipe Bot: %r", config)  # secrets are hidden from repr
    for warning in config.warnings():
        log.warning(warning)
    if not startup_checks(config):
        return 1

    bot = RecipeBot(config)
    try:
        bot.run(config.discord_token, log_handler=None)
    except discord.LoginFailure:
        log.error("Discord rejected DISCORD_TOKEN. Reset the token in the Developer Portal and update .env.")
        return 1
    except discord.PrivilegedIntentsRequired:
        log.error(
            "Message Content intent is off. In the Developer Portal open your app > Bot, "
            "turn on MESSAGE CONTENT INTENT, save, and start the bot again."
        )
        return 1
    except aiohttp.ClientConnectorError as exc:
        log.error("Couldn't reach Discord (%s). Check the internet connection and try again.", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
