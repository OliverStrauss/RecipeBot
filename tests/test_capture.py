"""The capture flow with Discord, yt-dlp, ffmpeg and Claude faked out; the DB is real (in memory)."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from recipe_bot.cogs import capture as capture_module
from recipe_bot.cogs.capture import Capture, Job
from recipe_bot.config import load_config
from recipe_bot.db import Database
from recipe_bot.pipeline import Media, PipelineError
from recipe_bot.pipeline.download import VideoMeta
from recipe_bot.pipeline.extract import ExtractionResult
from recipe_bot.pipeline.queue import JobQueue
from recipe_bot.pipeline.urls import VideoLink, normalize
from tests.test_db import recipe

URL = "https://www.tiktok.com/@chef/video/1"


def fake_message(guild_id=1, channel_id=555, author_id=10, content=URL):
    msg = MagicMock()
    msg.guild.id, msg.channel.id, msg.author.id, msg.author.bot = guild_id, channel_id, author_id, False
    msg.content, msg.thread = content, None
    msg.thread_obj = MagicMock(send=AsyncMock())
    msg.create_thread = AsyncMock(return_value=msg.thread_obj)
    for name in ("reply", "add_reaction", "remove_reaction"):
        setattr(msg, name, AsyncMock())
    return msg


@pytest.fixture
async def cog(tmp_path, monkeypatch):
    db = Database(Path(":memory:"))
    await db.connect()
    config = load_config({"DISCORD_TOKEN": "x", "TEMP_DIR": str(tmp_path / "tmp"), "DEFAULT_DAILY_LIMIT": "3"})
    backend = SimpleNamespace(name="claude_cli", extract=AsyncMock(return_value=ExtractionResult(
        recipe("Chicken Soup", ["chicken", "carrots"], ["soup"]), 1000, 200, 0.05, "{}")))
    bot = SimpleNamespace(db=db, config=config, backend=backend, user=object())
    c = Capture(bot)
    bot.queue = JobQueue(c.process)

    async def fake_fetch(url, platform, job_dir, config):
        (job_dir / "video.mp4").write_bytes(b"v")
        return job_dir / "video.mp4", VideoMeta(platform, url, "caption", "chef", None, 30)

    async def fake_prepare(video, meta, job_dir, config):
        return Media(video, meta, "transcript", [])

    monkeypatch.setattr(capture_module, "fetch", fake_fetch)
    monkeypatch.setattr(capture_module, "prepare", fake_prepare)
    await db.set_recipe_channel(1, 555)
    yield c
    await db.close()


def job(cog, msg, job_id, url=URL):
    return Job(job_id, msg.guild.id, msg.author.id, normalize(url), msg)


def reactions(msg):
    return [c.args[0] for c in msg.add_reaction.await_args_list]


async def test_process_saves_and_replies_in_thread(cog):
    msg = fake_message()
    job_id = await cog.bot.db.create_job(1, 10, URL, "claude_cli")
    await cog.process(job(cog, msg, job_id))

    saved = await cog.bot.db.find_by_url(1, URL)
    assert saved.recipe.title == "Chicken Soup" and saved.submitter_id == 10 and saved.creator == "chef"
    msg.create_thread.assert_awaited_once_with(name="Chicken Soup")
    embed = msg.thread_obj.send.await_args.kwargs["embed"]
    assert f"Recipe #{saved.id}" in embed.description
    assert reactions(msg) == ["✅"]
    row = await cog.bot.db._one("SELECT status, input_tokens, output_tokens, backend FROM jobs WHERE id=?", (job_id,))
    assert row == ("done", 1000, 200, "claude_cli")
    assert not list(cog.bot.config.temp_dir.iterdir())  # temp files cleaned up


async def test_thread_failure_falls_back_to_reply(cog):
    import discord
    msg = fake_message()
    msg.create_thread.side_effect = discord.HTTPException(MagicMock(status=400), "in a thread")
    await cog.process(job(cog, msg, await cog.bot.db.create_job(1, 10, URL, "x")))
    assert "embed" in msg.reply.await_args.kwargs


async def test_pipeline_error_is_reported(cog, monkeypatch):
    async def broken_fetch(*a):
        raise PipelineError("That video is private or no longer available.")
    monkeypatch.setattr(capture_module, "fetch", broken_fetch)
    msg = fake_message()
    job_id = await cog.bot.db.create_job(1, 10, URL, "x")

    await cog.process(job(cog, msg, job_id))

    assert msg.reply.await_args.args[0] == "❌ That video is private or no longer available."
    assert reactions(msg) == ["❌"]
    assert await cog.bot.db.find_by_url(1, URL) is None
    row = await cog.bot.db._one("SELECT status, error FROM jobs WHERE id=?", (job_id,))
    assert row == ("failed", "That video is private or no longer available.")


async def test_not_a_recipe(cog):
    cog.bot.backend.extract.return_value.recipe = recipe("Kitchen tour", [], []).model_copy(update={"is_recipe": False})
    msg = fake_message()
    await cog.process(job(cog, msg, await cog.bot.db.create_job(1, 10, URL, "x")))
    assert "doesn't look like a recipe" in msg.reply.await_args.args[0]
    assert await cog.bot.db.find_by_url(1, URL) is None


async def test_unexpected_crash_is_reported_without_details(cog):
    cog.bot.backend.extract.side_effect = KeyError("boom")
    msg = fake_message()
    await cog.process(job(cog, msg, await cog.bot.db.create_job(1, 10, URL, "x")))
    assert "Something went wrong" in msg.reply.await_args.args[0] and "boom" not in msg.reply.await_args.args[0]


async def test_short_link_resolving_to_saved_video_skips_claude(cog, monkeypatch):
    async def resolving_fetch(url, platform, job_dir, config):  # yt-dlp reports the canonical URL
        return job_dir / "video.mp4", VideoMeta(platform, URL + "?lang=en", "caption", "chef", None, 30)
    monkeypatch.setattr(capture_module, "fetch", resolving_fetch)
    await cog.bot.db.save_recipe(guild_id=1, submitter_id=11, source_url=URL, platform="tiktok",
                                 creator="chef", recipe=recipe("Saved", [], []))
    msg = fake_message(content="https://vm.tiktok.com/ZMabc/")
    await cog.process(job(cog, msg, await cog.bot.db.create_job(1, 10, "short", "x"), "https://vm.tiktok.com/ZMabc/"))
    cog.bot.backend.extract.assert_not_awaited()
    assert "Already saved" in msg.reply.await_args.args[0]


async def test_checks_dedupe_queue_and_limit(cog):
    link = normalize(URL)
    assert await cog.check(1, 10, link) == (None, None)
    await cog.bot.db.create_job(1, 10, link.url, "x")
    assert "already in the queue" in (await cog.check(1, 10, link))[1]
    for n in range(2):
        await cog.bot.db.create_job(1, 10, f"other{n}", "x")
    assert "limit of 3" in (await cog.check(1, 10, VideoLink("tiktok", "new")))[1]
    assert (await cog.check(1, 99, VideoLink("tiktok", "new"))) == (None, None)  # per user
    saved = await cog.bot.db.save_recipe(guild_id=1, submitter_id=11, source_url=link.url, platform="tiktok",
                                         creator=None, recipe=recipe("Saved", [], []))
    assert (await cog.check(1, 10, link))[0].id == saved.id  # dedupe wins over the limit


async def test_three_links_processed_in_order_with_positions(cog):
    """M6: links posted quickly queue up, get positions, and run one at a time in order."""
    urls = [f"https://www.tiktok.com/@chef/video/{n}" for n in (1, 2, 3)]
    msgs = [fake_message(content=u) for u in urls]
    for m in msgs:
        await cog.on_message(m)  # workers not started yet, so everything waits

    assert [reactions(m) for m in msgs] == [["⏳"], ["⏳"], ["⏳"]]
    msgs[0].reply.assert_not_awaited()
    assert msgs[1].reply.await_args.args[0] == "⏳ Queued. 1 video ahead of you."
    assert msgs[2].reply.await_args.args[0] == "⏳ Queued. 2 videos ahead of you."

    cog.bot.queue.start()
    await asyncio.wait_for(cog.bot.queue.join(), 5)
    await cog.bot.queue.stop()

    processed = [c.args[0] for c in cog.bot.backend.extract.await_args_list]
    assert processed == ["caption"] * 3
    titles_in_order = [(await cog.bot.db.find_by_url(1, u)).id for u in urls]
    assert titles_in_order == sorted(titles_in_order)
    assert all(reactions(m)[-1] == "✅" for m in msgs)


async def test_links_outside_recipe_channel_ignored(cog):
    msg = fake_message(channel_id=999)
    await cog.on_message(msg)
    msg.add_reaction.assert_not_awaited()
    assert cog.bot.queue.waiting == 0


async def test_delete_only_own_unless_admin(cog):
    """M5: two users save recipes, both can see them, each can delete only their own."""
    db = cog.bot.db
    alice = await db.save_recipe(guild_id=1, submitter_id=10, source_url="a", platform="tiktok",
                                 creator=None, recipe=recipe("Alice's", [], []))
    bob = await db.save_recipe(guild_id=1, submitter_id=20, source_url="b", platform="tiktok",
                               creator=None, recipe=recipe("Bob's", [], []))

    def interaction(user_id, admin=False):
        i = MagicMock(guild_id=1)
        i.user.id = user_id
        i.permissions.manage_guild = admin
        i.response.send_message = AsyncMock()
        return i

    seen = interaction(10)
    await cog.show.callback(cog, seen, id=bob.id)
    assert "Bob's" in seen.response.send_message.await_args.kwargs["embed"].title

    denied = interaction(10)
    await cog.delete.callback(cog, denied, id=bob.id)
    assert "Only the person who saved it" in denied.response.send_message.await_args.args[0]
    assert await db.get_recipe(1, bob.id) is not None

    await cog.delete.callback(cog, interaction(10), id=alice.id)
    assert await db.get_recipe(1, alice.id) is None

    await cog.delete.callback(cog, interaction(30, admin=True), id=bob.id)
    assert await db.get_recipe(1, bob.id) is None
