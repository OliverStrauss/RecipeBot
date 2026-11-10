"""The Bot subclass: intents, cog loading and slash-command sync."""

from __future__ import annotations

import logging
import shutil
import time

import discord
from aiohttp import web
from discord.ext import commands

from .config import Config
from .db import Database
from .pipeline.extract import ExtractionBackend, get_backend
from .pipeline.queue import JobQueue
from .web import make_app

log = logging.getLogger(__name__)

# The bot never joins voice, so silence discord.py's "voice will NOT be supported" warnings.
discord.VoiceClient.warn_nacl = False
if hasattr(discord.VoiceClient, "warn_dave"):
    discord.VoiceClient.warn_dave = False

EXTENSIONS = (
    "recipe_bot.cogs.admin",
    "recipe_bot.cogs.capture",
    "recipe_bot.cogs.library",
)


def build_intents() -> discord.Intents:
    intents = discord.Intents.default()
    # Privileged: needed to read links posted in the recipe channel (M5).
    # Must also be switched on in the Developer Portal (Bot > Message Content Intent).
    intents.message_content = True
    return intents


class RecipeBot(commands.Bot):
    def __init__(self, config: Config):
        super().__init__(
            # Slash commands only; mention-prefix keeps discord.py happy without
            # claiming a text prefix like "!" that could clash with other bots.
            command_prefix=commands.when_mentioned,
            intents=build_intents(),
            help_command=None,
            # Every command needs a server: libraries, limits and settings are per server.
            allowed_contexts=discord.app_commands.AppCommandContext(guild=True),
        )
        self.config = config
        self.started_at = time.monotonic()
        self.db = Database(config.db_path)
        self.backend: ExtractionBackend = get_backend(config)
        self.queue: JobQueue  # created by the capture cog, which owns the worker
        self.web: web.AppRunner | None = None

    async def setup_hook(self) -> None:
        await self.db.connect()
        if self.config.web_url:
            self.web = web.AppRunner(make_app(self.db))
            await self.web.setup()
            await web.TCPSite(self.web, port=self.config.web_port).start()
            log.info("Recipe pages on port %d, linked as %s", self.config.web_port, self.config.web_url)
        # Leftovers from a crash mid-job. Only job-* dirs, in case TEMP_DIR is shared.
        for leftover in self.config.temp_dir.glob("job-*"):
            shutil.rmtree(leftover, ignore_errors=True)
        for ext in EXTENSIONS:
            await self.load_extension(ext)
            log.info("Loaded %s", ext)
        await self.sync_commands()

    async def sync_commands(self) -> list[discord.app_commands.AppCommand]:
        """Sync slash commands.

        With DEV_GUILD_ID set, commands are copied to that one server, where they
        show up instantly. Without it they sync globally, which Discord can take
        up to an hour to roll out.
        """
        if self.config.dev_guild_id:
            guild = discord.Object(id=self.config.dev_guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %d command(s) to dev guild %s", len(synced), self.config.dev_guild_id)
        else:
            synced = await self.tree.sync()
            log.info("Synced %d command(s) globally (can take up to an hour to appear)", len(synced))
        return synced

    async def on_ready(self) -> None:
        assert self.user is not None
        log.info(
            "Online as %s (id %s) in %d server(s). Backend: %s",
            self.user, self.user.id, len(self.guilds), self.config.claude_backend,
        )

    async def close(self) -> None:
        await super().close()  # unloads cogs, which stops the queue workers
        if self.web:
            await self.web.cleanup()
        await self.db.close()

    @property
    def uptime_seconds(self) -> float:
        return time.monotonic() - self.started_at
