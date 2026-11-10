"""Load and validate settings from environment variables (and .env).

Every setting lives in one frozen ``Config`` object. ``load_config`` collects
*all* problems before failing, so a bad .env is fixed in one pass instead of
one error at a time.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

BACKENDS = ("claude_cli", "api")
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


class ConfigError(Exception):
    """Raised when one or more settings are missing or invalid."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("Invalid configuration:\n" + "\n".join(f"  - {p}" for p in problems))


@dataclass(frozen=True)
class Config:
    # Secrets are excluded from repr so they never end up in logs.
    discord_token: str = field(repr=False)
    claude_backend: str = "claude_cli"
    claude_model: str | None = None
    claude_code_oauth_token: str | None = field(default=None, repr=False)
    claude_cli_path: str = "claude"
    claude_cli_timeout_seconds: int = 180
    anthropic_api_key: str | None = field(default=None, repr=False)
    whisper_model: str = "base"
    ig_cookies_path: Path | None = None
    db_path: Path = Path("./data/recipes.db")
    temp_dir: Path = Path("./data/tmp")
    max_video_seconds: int = 600
    max_frames: int = 20
    frame_interval_seconds: int = 2
    default_daily_limit: int = 15
    worker_concurrency: int = 1
    dev_guild_id: int | None = None
    log_level: str = "INFO"
    web_url: str | None = None  # public base URL of the recipe pages; None = no web server
    web_port: int = 8080

    def warnings(self) -> list[str]:
        """Non-fatal issues worth a loud log line at startup."""
        out: list[str] = []
        if self.claude_backend == "claude_cli":
            if self.anthropic_api_key:
                out.append(
                    "CLAUDE_BACKEND=claude_cli but ANTHROPIC_API_KEY is set. The Claude CLI "
                    "will use the API key and bill API usage instead of your subscription. "
                    "Remove ANTHROPIC_API_KEY from the environment."
                )
            if not self.claude_code_oauth_token:
                out.append(
                    "CLAUDE_CODE_OAUTH_TOKEN is empty. That's fine if `claude` is already "
                    "signed in on this machine; otherwise run `claude setup-token`."
                )
        return out


def _clean(value: str | None) -> str | None:
    """Treat unset, empty and whitespace-only values the same: None."""
    if value is None:
        return None
    value = value.strip()
    return value or None


def load_config(env: Mapping[str, str] | None = None) -> Config:
    """Build a Config from ``env`` (defaults to ``os.environ``).

    Call ``dotenv.load_dotenv()`` first if you want a .env file picked up;
    keeping that out of here makes this function easy to test.
    """
    env = os.environ if env is None else env
    problems: list[str] = []

    def get(name: str) -> str | None:
        return _clean(env.get(name))

    def get_int(name: str, default: int, minimum: int = 1) -> int:
        raw = get(name)
        if raw is None:
            return default
        try:
            value = int(raw)
        except ValueError:
            problems.append(f"{name} must be a whole number (got {raw!r}).")
            return default
        if value < minimum:
            problems.append(f"{name} must be at least {minimum} (got {value}).")
            return default
        return value

    token = get("DISCORD_TOKEN")
    if token is None:
        problems.append(
            "DISCORD_TOKEN is missing. Copy it from the Discord Developer Portal "
            "(your app > Bot > Reset Token) into .env."
        )

    backend = (get("CLAUDE_BACKEND") or "claude_cli").lower()
    if backend not in BACKENDS:
        problems.append(f"CLAUDE_BACKEND must be one of {', '.join(BACKENDS)} (got {backend!r}).")
    elif backend == "api" and not get("ANTHROPIC_API_KEY"):
        problems.append("CLAUDE_BACKEND=api needs ANTHROPIC_API_KEY (from console.anthropic.com).")

    log_level = (get("LOG_LEVEL") or "INFO").upper()
    if log_level not in LOG_LEVELS:
        problems.append(f"LOG_LEVEL must be one of {', '.join(LOG_LEVELS)} (got {log_level!r}).")

    dev_guild_id: int | None = None
    raw_guild = get("DEV_GUILD_ID")
    if raw_guild is not None:
        if raw_guild.isdigit():
            dev_guild_id = int(raw_guild)
        else:
            problems.append(
                f"DEV_GUILD_ID must be a numeric server ID (got {raw_guild!r}). "
                "Enable Developer Mode in Discord, then right-click the server > Copy Server ID."
            )

    cookies = get("IG_COOKIES_PATH")

    web_url = get("WEB_URL")
    if web_url and not web_url.startswith(("http://", "https://")):
        problems.append(f"WEB_URL must start with http:// or https:// (got {web_url!r}).")

    config = Config(
        discord_token=token or "",
        claude_backend=backend,
        claude_model=get("CLAUDE_MODEL"),
        claude_code_oauth_token=get("CLAUDE_CODE_OAUTH_TOKEN"),
        claude_cli_path=get("CLAUDE_CLI_PATH") or "claude",
        claude_cli_timeout_seconds=get_int("CLAUDE_CLI_TIMEOUT_SECONDS", 180),
        anthropic_api_key=get("ANTHROPIC_API_KEY"),
        whisper_model=get("WHISPER_MODEL") or "base",
        ig_cookies_path=Path(cookies).expanduser() if cookies else None,
        db_path=Path(get("DB_PATH") or "./data/recipes.db").expanduser(),
        temp_dir=Path(get("TEMP_DIR") or "./data/tmp").expanduser(),
        max_video_seconds=get_int("MAX_VIDEO_SECONDS", 600),
        max_frames=get_int("MAX_FRAMES", 20),
        frame_interval_seconds=get_int("FRAME_INTERVAL_SECONDS", 2),
        default_daily_limit=get_int("DEFAULT_DAILY_LIMIT", 15),
        worker_concurrency=get_int("WORKER_CONCURRENCY", 1),
        dev_guild_id=dev_guild_id,
        log_level=log_level,
        web_url=web_url.rstrip("/") if web_url else None,
        web_port=get_int("WEB_PORT", 8080),
    )

    if problems:
        raise ConfigError(problems)
    return config


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # discord.py's gateway chatter is noisy at DEBUG; keep it at INFO unless asked.
    if level != "DEBUG":
        logging.getLogger("discord").setLevel(logging.INFO)
