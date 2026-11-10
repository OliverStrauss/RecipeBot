"""Link capture: auto-processing in the recipe channel, /recipe add|show|delete, and the job worker.

(/recipe show and delete live here rather than in library.py because discord.py
wants one command group per cog.)
"""

from __future__ import annotations

import logging
import shutil
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..models import SavedRecipe
from ..pipeline import PipelineError, fetch, prepare
from ..pipeline.queue import JobQueue
from ..pipeline.urls import VideoLink, find_links, normalize
from ..render import recipe_embed

if TYPE_CHECKING:
    from ..bot import RecipeBot

log = logging.getLogger(__name__)

QUEUED, DONE, FAILED = "⏳", "✅", "❌"


@dataclass
class Job:
    id: int
    guild_id: int
    user_id: int
    link: VideoLink
    message: discord.Message  # gets the reactions and replies
    status_message: discord.Message | None = None  # "N ahead of you", deleted when the job starts


async def _quietly(coro) -> None:
    """Discord calls that are nice-to-have (reactions, cleanup) must never kill a job."""
    with suppress(discord.HTTPException):
        await coro


class Capture(commands.Cog):
    recipe = app_commands.Group(name="recipe", description="Add, show or delete a saved recipe")

    def __init__(self, bot: RecipeBot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.queue = JobQueue(self.process, self.bot.config.worker_concurrency)
        self.bot.queue.start()

    async def cog_unload(self) -> None:
        await self.bot.queue.stop()

    # --- before queuing -------------------------------------------------------------------

    async def check(self, guild_id: int, user_id: int, link: VideoLink) -> tuple[SavedRecipe | None, str | None]:
        """Dedupe and rate-limit checks. Returns (existing recipe, refusal text); both None = go."""
        db = self.bot.db
        if existing := await db.find_by_url(guild_id, link.url):
            return existing, None
        if await db.active_job(guild_id, link.url):
            return None, "That video is already in the queue."
        limit = await db.daily_limit(guild_id, self.bot.config.default_daily_limit)
        if await db.jobs_last_24h(guild_id, user_id) >= limit:
            return None, (f"You've hit this server's limit of {limit} videos per 24 hours. "
                          "Try again a bit later!")
        return None, None

    async def enqueue(self, job_message: discord.Message, guild_id: int, user_id: int, link: VideoLink,
                      status_message: discord.Message | None = None) -> None:
        """Create the job row, react ⏳ and queue it."""
        job_id = await self.bot.db.create_job(guild_id, user_id, link.url, self.bot.backend.name)
        await _quietly(job_message.add_reaction(QUEUED))
        self.bot.queue.submit(Job(job_id, guild_id, user_id, link, job_message, status_message))
        log.info("Queued job %s: %s", job_id, link.url)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        links = find_links(message.content)
        if not links or message.channel.id != await self.bot.db.recipe_channel(message.guild.id):
            return
        for link in links:
            existing, refusal = await self.check(message.guild.id, message.author.id, link)
            if existing:
                await self.reply_existing(message, existing)
            elif refusal:
                await _quietly(message.reply(refusal, mention_author=False))
            else:
                status = None
                if ahead := self.bot.queue.ahead:
                    with suppress(discord.HTTPException):
                        status = await message.reply(f"{QUEUED} Queued. {_ahead(ahead)}", mention_author=False)
                await self.enqueue(message, message.guild.id, message.author.id, link, status)

    async def reply_existing(self, message: discord.Message, saved: SavedRecipe) -> None:
        embed, file = recipe_embed(saved, self.bot.config.web_url)
        await _quietly(message.reply(
            f"Already saved as Recipe #{saved.id}.", embed=embed, mention_author=False,
            **({"file": file} if file else {})))

    # --- slash commands ---------------------------------------------------------------------

    @recipe.command(name="add", description="Turn a TikTok or Instagram video into a recipe")
    @app_commands.describe(url="Link to the TikTok or Instagram video")
    async def add(self, interaction: discord.Interaction, url: str) -> None:
        link = normalize(url)
        if link is None:
            await interaction.response.send_message(
                "That doesn't look like a TikTok or Instagram video link.", ephemeral=True)
            return
        existing, refusal = await self.check(interaction.guild_id, interaction.user.id, link)
        if refusal:
            await interaction.response.send_message(refusal, ephemeral=True)
            return
        if existing:
            embed, file = recipe_embed(existing, self.bot.config.web_url)
            await interaction.response.send_message(
                f"Already saved as Recipe #{existing.id}.", embed=embed, **({"file": file} if file else {}))
            return
        # A public message gives the job something to react on and reply to.
        ahead = self.bot.queue.ahead
        await interaction.response.send_message(
            f"{QUEUED} Queued <{link.url}>. {_ahead(ahead)}" if ahead else f"{QUEUED} Working on <{link.url}>")
        await self.enqueue(await interaction.original_response(), interaction.guild_id, interaction.user.id, link)

    @recipe.command(name="show", description="Show a saved recipe")
    @app_commands.describe(id="Recipe number, e.g. 42")
    async def show(self, interaction: discord.Interaction, id: int) -> None:
        saved = await self.bot.db.get_recipe(interaction.guild_id, id)
        if saved is None:
            await interaction.response.send_message(f"No recipe #{id} in this server.", ephemeral=True)
            return
        embed, file = recipe_embed(saved, self.bot.config.web_url)
        await interaction.response.send_message(embed=embed, **({"file": file} if file else {}))

    @recipe.command(name="delete", description="Delete a recipe (yours, or any if you can manage the server)")
    @app_commands.describe(id="Recipe number, e.g. 42")
    async def delete(self, interaction: discord.Interaction, id: int) -> None:
        saved = await self.bot.db.get_recipe(interaction.guild_id, id)
        if saved is None:
            await interaction.response.send_message(f"No recipe #{id} in this server.", ephemeral=True)
            return
        if saved.submitter_id != interaction.user.id and not interaction.permissions.manage_guild:
            await interaction.response.send_message(
                "Only the person who saved it, or someone with Manage Server, can delete it.", ephemeral=True)
            return
        await self.bot.db.delete_recipe(interaction.guild_id, id)
        await interaction.response.send_message(f"Deleted Recipe #{id}: {saved.recipe.title}.", ephemeral=True)

    # --- the worker ---------------------------------------------------------------------------

    async def process(self, job: Job) -> None:
        db, config = self.bot.db, self.bot.config
        if job.status_message:
            await _quietly(job.status_message.delete())
        await db.job_running(job.id)
        job_dir = config.temp_dir / f"job-{job.id}"
        job_dir.mkdir(parents=True, exist_ok=True)
        result = None
        try:
            video, meta = await fetch(job.link.url, job.link.platform, job_dir, config)
            # Short links only resolve now; the canonical URL may already be saved.
            url = (normalize(meta.url) or job.link).url
            if url != job.link.url and (existing := await db.find_by_url(job.guild_id, url)):
                await db.finish_job(job.id)
                await self.reply_existing(job.message, existing)
                await self.react(job, DONE)
                return
            media = await prepare(video, meta, job_dir, config)
            result = await self.bot.backend.extract(meta.caption, media.transcript, media.frames, meta, job_dir)
            log.info("Job %s usage: backend=%s in=%s out=%s cost=%s", job.id, self.bot.backend.name,
                     result.input_tokens, result.output_tokens, result.cost_usd)
            if not result.recipe.is_recipe:
                raise PipelineError("That video doesn't look like a recipe.")
            saved = await db.save_recipe(
                guild_id=job.guild_id, submitter_id=job.user_id, source_url=url,
                platform=job.link.platform, creator=meta.creator, recipe=result.recipe)
            await db.finish_job(job.id, input_tokens=result.input_tokens, output_tokens=result.output_tokens)
            await self.post(job, saved)
            await self.react(job, DONE)
        except Exception as exc:
            if isinstance(exc, PipelineError):
                reason = str(exc)
            else:
                log.exception("Job %s failed", job.id)
                reason = "Something went wrong on my end (details are in the bot's log)."
            await db.finish_job(job.id, error=reason[:500],
                                input_tokens=result and result.input_tokens,
                                output_tokens=result and result.output_tokens)
            await _quietly(job.message.reply(f"{FAILED} {reason}", mention_author=False))
            await self.react(job, FAILED)
        finally:
            shutil.rmtree(job_dir, ignore_errors=True)

    async def post(self, job: Job, saved: SavedRecipe) -> None:
        """Post to the cookbook channel if one is set and reachable, else reply to the link."""
        if await self.post_to_cookbook(job, saved):
            return
        embed, file = recipe_embed(saved, self.bot.config.web_url)  # fresh File: a failed cookbook send may have consumed the last one
        await job.message.reply(embed=embed, mention_author=False, **({"file": file} if file else {}))

    async def post_to_cookbook(self, job: Job, saved: SavedRecipe) -> bool:
        channel_id = await self.bot.db.cookbook_channel(job.guild_id)
        channel = channel_id and self.bot.get_channel(channel_id)
        if not channel:  # not set, or the channel was deleted
            return False
        embed, file = recipe_embed(saved, self.bot.config.web_url)
        try:
            posted = await channel.send(embed=embed, **({"file": file} if file else {}))
        except discord.HTTPException as exc:
            log.warning("Can't post to cookbook channel %s (%s); replying to the link instead", channel_id, exc)
            return False
        await _quietly(job.message.reply(f"Saved as Recipe #{saved.id}: {posted.jump_url}", mention_author=False))
        return True

    async def react(self, job: Job, emoji: str) -> None:
        await _quietly(job.message.remove_reaction(QUEUED, self.bot.user))
        await _quietly(job.message.add_reaction(emoji))


def _ahead(n: int) -> str:
    return f"{n} video{'s' if n != 1 else ''} ahead of you."


async def setup(bot: RecipeBot) -> None:
    await bot.add_cog(Capture(bot))
