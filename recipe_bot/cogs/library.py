"""Browsing the server's library: /recipes search|mine|recent|random."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..render import list_pages, recipe_embed

if TYPE_CHECKING:
    from ..bot import RecipeBot


class Paginator(discord.ui.View):
    """◀ ▶ buttons over a list of embeds. Buttons disappear after 5 idle minutes."""

    def __init__(self, pages: list[discord.Embed]):
        super().__init__(timeout=300)
        self.pages, self.index = pages, 0
        self.message: discord.InteractionMessage | None = None
        self._sync()

    def _sync(self) -> None:
        self.prev.disabled = self.index == 0
        self.next.disabled = self.index == len(self.pages) - 1

    async def _show(self, interaction: discord.Interaction, delta: int) -> None:
        self.index += delta
        self._sync()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._show(interaction, -1)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._show(interaction, +1)

    async def on_timeout(self) -> None:
        if self.message:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass


async def send_pages(interaction: discord.Interaction, pages: list[discord.Embed]) -> None:
    if len(pages) == 1:
        await interaction.response.send_message(embed=pages[0])
        return
    view = Paginator(pages)
    await interaction.response.send_message(embed=pages[0], view=view)
    view.message = await interaction.original_response()


class Library(commands.Cog):
    recipes = app_commands.Group(name="recipes", description="Browse this server's recipes")

    def __init__(self, bot: RecipeBot):
        self.bot = bot

    @recipes.command(name="search", description="Search titles, tags and ingredients")
    @app_commands.describe(query="e.g. chicken thighs, air fryer, vegetarian")
    async def search(self, interaction: discord.Interaction, query: str) -> None:
        found = await self.bot.db.search(interaction.guild_id, query)
        if not found:
            await interaction.response.send_message(f"No recipes match “{query}”.", ephemeral=True)
            return
        await send_pages(interaction, list_pages(found, f"Recipes matching “{query[:100]}”"))

    @recipes.command(name="mine", description="Recipes you saved")
    async def mine(self, interaction: discord.Interaction) -> None:
        mine = await self.bot.db.recipes_by(interaction.guild_id, interaction.user.id)
        await send_pages(interaction, list_pages(mine, f"Saved by {interaction.user.display_name}"))

    @recipes.command(name="recent", description="The latest 10 recipes in this server")
    async def recent(self, interaction: discord.Interaction) -> None:
        await send_pages(interaction, list_pages(await self.bot.db.recent(interaction.guild_id), "Recent recipes"))

    @recipes.command(name="random", description="What should I make tonight?")
    @app_commands.describe(tag="Only pick from recipes with this tag, e.g. dessert")
    async def random(self, interaction: discord.Interaction, tag: str | None = None) -> None:
        saved = await self.bot.db.random(interaction.guild_id, tag)
        if saved is None:
            text = f"No recipes tagged “{tag}” yet." if tag else "No recipes saved in this server yet."
            await interaction.response.send_message(text, ephemeral=True)
            return
        embed, file = recipe_embed(saved, self.bot.config.web_url)
        await interaction.response.send_message(
            "How about this one?", embed=embed, **({"file": file} if file else {}))


async def setup(bot: RecipeBot) -> None:
    await bot.add_cog(Library(bot))
