"""Admin commands: /status now; /setup channel and /setup limits arrive in M5/M6."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

if TYPE_CHECKING:
    from ..bot import RecipeBot


def format_uptime(seconds: float) -> str:
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def build_status_embed(
    *,
    backend: str,
    model: str | None,
    queue_length: int | None,
    usage_today: int | None,
    daily_limit: int,
    uptime_seconds: float,
    latency_ms: float | None,
) -> discord.Embed:
    """Pure function so /status output is unit-testable without Discord.

    ``queue_length`` and ``usage_today`` are None until the queue (M6) exists.
    """
    embed = discord.Embed(title="Recipe Bot status", colour=discord.Colour.green())
    embed.add_field(
        name="Queue",
        value="not built yet (M6)" if queue_length is None else f"{queue_length} waiting",
        inline=True,
    )
    embed.add_field(
        name="Your usage today",
        value=(
            f"not tracked yet (M6) · limit {daily_limit}/day"
            if usage_today is None
            else f"{usage_today}/{daily_limit}"
        ),
        inline=True,
    )
    backend_text = backend if not model else f"{backend} ({model})"
    embed.add_field(name="Claude backend", value=backend_text, inline=True)
    embed.add_field(name="Uptime", value=format_uptime(uptime_seconds), inline=True)
    if latency_ms is not None:
        embed.add_field(name="Latency", value=f"{latency_ms:.0f} ms", inline=True)
    return embed


class Admin(commands.Cog):
    def __init__(self, bot: RecipeBot):
        self.bot = bot

    @app_commands.command(name="status", description="Queue length, your usage today, and the active backend")
    async def status(self, interaction: discord.Interaction) -> None:
        latency = self.bot.latency
        embed = build_status_embed(
            backend=self.bot.config.claude_backend,
            model=self.bot.config.claude_model,
            queue_length=None,
            usage_today=None,
            daily_limit=self.bot.config.default_daily_limit,
            uptime_seconds=self.bot.uptime_seconds,
            # latency is inf/nan before the first heartbeat
            latency_ms=latency * 1000 if latency == latency and latency != float("inf") else None,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: RecipeBot) -> None:
    await bot.add_cog(Admin(bot))
