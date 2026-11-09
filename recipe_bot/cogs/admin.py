"""Admin commands: /setup channel, /setup cookbook, /setup limits, /status."""

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
    queue_length: int,
    usage_today: int,
    daily_limit: int,
    uptime_seconds: float,
    latency_ms: float | None,
) -> discord.Embed:
    """Pure function so /status output is unit-testable without Discord."""
    embed = discord.Embed(title="Recipe Bot status", colour=discord.Colour.green())
    embed.add_field(name="Queue", value=f"{queue_length} waiting", inline=True)
    embed.add_field(name="Your usage today", value=f"{usage_today}/{daily_limit}", inline=True)
    backend_text = backend if not model else f"{backend} ({model})"
    embed.add_field(name="Claude backend", value=backend_text, inline=True)
    embed.add_field(name="Uptime", value=format_uptime(uptime_seconds), inline=True)
    if latency_ms is not None:
        embed.add_field(name="Latency", value=f"{latency_ms:.0f} ms", inline=True)
    return embed


class Admin(commands.Cog):
    setup_group = app_commands.Group(
        name="setup", description="Configure Recipe Bot for this server",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    def __init__(self, bot: RecipeBot):
        self.bot = bot

    @setup_group.command(name="channel", description="Auto-process video links posted in this channel")
    @app_commands.describe(channel="The recipe channel")
    async def setup_channel(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        await self.bot.db.set_recipe_channel(interaction.guild_id, channel.id)
        await interaction.response.send_message(
            f"Done. TikTok and Instagram links posted in {channel.mention} become recipes. "
            "Elsewhere, use `/recipe add`.", ephemeral=True)

    @setup_group.command(name="cookbook", description="Post finished recipes in this channel (leave empty to turn off)")
    @app_commands.describe(channel="Where recipes go. Leave empty to reply under each link instead.")
    async def setup_cookbook(self, interaction: discord.Interaction,
                             channel: discord.TextChannel | None = None) -> None:
        await self.bot.db.set_cookbook_channel(interaction.guild_id, channel and channel.id)
        if channel is None:
            text = "Done. Recipes will be posted as a reply to each link."
        else:
            text = f"Done. Finished recipes will be posted in {channel.mention}."
            perms = channel.permissions_for(interaction.guild.me)
            if not (perms.view_channel and perms.send_messages and perms.embed_links and perms.attach_files):
                text += (f"\n⚠ I can't post there yet. Give me View Channel, Send Messages, Embed Links and "
                         f"Attach Files in {channel.mention}. Until then, recipes are posted as replies.")
        await interaction.response.send_message(text, ephemeral=True)

    @setup_group.command(name="limits", description="How many videos each person can add per 24 hours")
    @app_commands.describe(daily="Videos per person per 24 hours")
    async def setup_limits(self, interaction: discord.Interaction,
                           daily: app_commands.Range[int, 1, 500]) -> None:
        await self.bot.db.set_daily_limit(interaction.guild_id, daily)
        await interaction.response.send_message(f"Done. Each person can add {daily} videos per 24 hours.",
                                                ephemeral=True)

    @app_commands.command(name="status", description="Queue length, your usage today, and the active backend")
    async def status(self, interaction: discord.Interaction) -> None:
        latency = self.bot.latency
        db = self.bot.db
        embed = build_status_embed(
            backend=self.bot.config.claude_backend,
            model=self.bot.config.claude_model,
            queue_length=self.bot.queue.waiting,
            usage_today=await db.jobs_last_24h(interaction.guild_id, interaction.user.id),
            daily_limit=await db.daily_limit(interaction.guild_id, self.bot.config.default_daily_limit),
            uptime_seconds=self.bot.uptime_seconds,
            # latency is inf/nan before the first heartbeat
            latency_ms=latency * 1000 if latency == latency and latency != float("inf") else None,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: RecipeBot) -> None:
    await bot.add_cog(Admin(bot))
