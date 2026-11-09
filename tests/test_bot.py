from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from recipe_bot.bot import RecipeBot, build_intents
from recipe_bot.cogs.admin import build_status_embed, format_uptime
from recipe_bot.config import load_config


def make_bot(**env) -> RecipeBot:
    return RecipeBot(load_config({"DISCORD_TOKEN": "abc", **env}))


def test_message_content_intent_enabled():
    intents = build_intents()
    assert intents.message_content
    assert intents.guilds


async def test_setup_hook_loads_status_and_syncs_to_dev_guild(monkeypatch):
    bot = make_bot(DEV_GUILD_ID="42")
    sync = AsyncMock(return_value=[object()])
    monkeypatch.setattr(bot.tree, "sync", sync)

    await bot.setup_hook()

    assert "Admin" in bot.cogs
    assert bot.tree.get_command("status") is not None
    sync.assert_awaited_once()
    guild = sync.await_args.kwargs["guild"]
    assert guild.id == 42
    # copy_global_to put /status on the dev guild
    assert bot.tree.get_command("status", guild=discord.Object(id=42)) is not None
    await bot.close()


async def test_setup_hook_syncs_globally_without_dev_guild(monkeypatch):
    bot = make_bot()
    sync = AsyncMock(return_value=[])
    monkeypatch.setattr(bot.tree, "sync", sync)

    await bot.setup_hook()

    sync.assert_awaited_once_with()
    await bot.close()


async def test_status_command_replies_ephemerally(monkeypatch):
    bot = make_bot(CLAUDE_MODEL="claude-sonnet-5-5")
    monkeypatch.setattr(bot.tree, "sync", AsyncMock(return_value=[]))
    await bot.setup_hook()

    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()
    command = bot.tree.get_command("status")
    await command.callback(bot.get_cog("Admin"), interaction)

    interaction.response.send_message.assert_awaited_once()
    kwargs = interaction.response.send_message.await_args.kwargs
    assert kwargs["ephemeral"] is True
    fields = {f.name: f.value for f in kwargs["embed"].fields}
    assert fields["Claude backend"] == "claude_cli (claude-sonnet-5-5)"
    assert "Latency" not in fields  # not connected, so no heartbeat yet
    await bot.close()


def test_status_embed_with_queue_numbers():
    embed = build_status_embed(
        backend="api", model=None, queue_length=3, usage_today=2,
        daily_limit=15, uptime_seconds=3725, latency_ms=87.4,
    )
    fields = {f.name: f.value for f in embed.fields}
    assert fields["Queue"] == "3 waiting"
    assert fields["Your usage today"] == "2/15"
    assert fields["Claude backend"] == "api"
    assert fields["Uptime"] == "1h 2m"
    assert fields["Latency"] == "87 ms"


@pytest.mark.parametrize("seconds, expected", [
    (5, "5s"), (65, "1m 5s"), (3600, "1h 0m"), (90061, "1d 1h 1m"),
])
def test_format_uptime(seconds, expected):
    assert format_uptime(seconds) == expected
