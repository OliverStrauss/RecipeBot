"""Recipe -> Discord embed (with a .md fallback) and -> Markdown."""

from __future__ import annotations

import io

import discord

from .models import Ingredient, Recipe, SavedRecipe

# Discord limits: embed description 4096 chars, whole embed 6000, title 256.
DESCRIPTION_LIMIT = 4096
EMBED_LIMIT = 6000
TITLE_LIMIT = 256

PLATFORMS = {"tiktok": "TikTok", "instagram": "Instagram"}
COLOURS = {"high": discord.Colour.green(), "medium": discord.Colour.gold(), "low": discord.Colour.orange()}


def format_ingredient(i: Ingredient) -> str:
    amount = " ".join(x for x in (i.quantity, i.unit) if x)
    text = f"{'~' if amount and i.estimated else ''}{amount} {i.item}".strip()
    if i.note:
        text += f", {i.note}"
    return text + (" (est.)" if i.estimated else "")


def _groups(recipe: Recipe) -> dict[str | None, list[Ingredient]]:
    groups: dict[str | None, list[Ingredient]] = {}
    for ing in recipe.ingredients:
        groups.setdefault(ing.group, []).append(ing)
    return groups


def meta_line(recipe: Recipe) -> str:
    parts = []
    if recipe.servings:
        parts.append(f"Serves {recipe.servings}")
    if recipe.prep_minutes:
        parts.append(f"Prep {recipe.prep_minutes} min")
    if recipe.cook_minutes:
        parts.append(f"Cook {recipe.cook_minutes} min")
    return " · ".join(parts)


def warning_line(recipe: Recipe) -> str:
    if recipe.confidence == "high":
        return ""
    return f"⚠ Confidence: {recipe.confidence}." + (f" {recipe.confidence_note}" if recipe.confidence_note else "")


def credit_line(saved: SavedRecipe) -> str:
    creator = f"[@{saved.creator}]({saved.source_url})" if saved.creator else f"[this video]({saved.source_url})"
    return (f"From {creator} on {PLATFORMS.get(saved.platform, saved.platform)} · "
            f"saved by <@{saved.submitter_id}> · Recipe #{saved.id}")


def _step(n: int, text: str, minutes: int | None) -> str:
    return f"{n}. {text}" + (f" (~{minutes} min)" if minutes else "")


def _body(recipe: Recipe) -> str:
    out = ["**Ingredients**"]
    for group, items in _groups(recipe).items():
        if group:
            out.append(f"*{group}*")
        out += [f"- {format_ingredient(i)}" for i in items]
    out += ["", "**Steps**"]
    out += [_step(s.number, s.text, s.duration_minutes) for s in recipe.steps]
    if recipe.tips:
        out += ["", "**Tips**", *(f"- {t}" for t in recipe.tips)]
    return "\n".join(out)


def recipe_embed(saved: SavedRecipe) -> tuple[discord.Embed, discord.File | None]:
    """The full recipe as one embed, or a short embed plus a .md file when it won't fit."""
    recipe = saved.recipe
    head = [recipe.description, meta_line(recipe), warning_line(recipe)]
    embed = discord.Embed(
        title=recipe.title[:TITLE_LIMIT], url=saved.source_url, colour=COLOURS[recipe.confidence],
        description="\n\n".join(p for p in [*head, _body(recipe), credit_line(saved)] if p),
    )
    if recipe.tags:
        embed.set_footer(text="Tags: " + ", ".join(recipe.tags))
    if len(embed.description) <= DESCRIPTION_LIMIT and len(embed) <= EMBED_LIMIT:
        return embed, None

    embed.description = "\n\n".join(
        p for p in [*head, "The full recipe didn't fit in a message, so it's attached as a file.",
                    credit_line(saved)] if p
    )[:DESCRIPTION_LIMIT]
    file = discord.File(io.BytesIO(recipe_markdown(saved).encode()), filename=f"recipe-{saved.id}.md")
    return embed, file


def recipe_markdown(saved: SavedRecipe) -> str:
    recipe = saved.recipe
    out = [f"# {recipe.title}", "", recipe.description]
    for line in (meta_line(recipe), warning_line(recipe)):
        if line:
            out += ["", line]
    out += ["", "## Ingredients"]
    for group, items in _groups(recipe).items():
        if group:
            out += ["", f"### {group}"]
        out += [f"- {format_ingredient(i)}" for i in items]
    out += ["", "## Steps", *(_step(s.number, s.text, s.duration_minutes) for s in recipe.steps)]
    if recipe.equipment:
        out += ["", "## Equipment", *(f"- {e}" for e in recipe.equipment)]
    if recipe.tips:
        out += ["", "## Tips", *(f"- {t}" for t in recipe.tips)]
    if recipe.tags:
        out += ["", "Tags: " + ", ".join(recipe.tags)]
    creator = f"@{saved.creator}" if saved.creator else "the creator"
    out += ["", f"Source: {creator} on {PLATFORMS.get(saved.platform, saved.platform)}, {saved.source_url}",
            f"Recipe #{saved.id}"]
    return "\n".join(out) + "\n"


def list_line(saved: SavedRecipe) -> str:
    by = f" · @{saved.creator}" if saved.creator else ""
    return f"`#{saved.id}` [{saved.recipe.title[:80]}]({saved.source_url}){by} · <@{saved.submitter_id}>"


def list_pages(items: list[SavedRecipe], title: str, per_page: int = 10) -> list[discord.Embed]:
    """Embeds of ``per_page`` one-line entries each, for the paginator."""
    chunks = [items[i:i + per_page] for i in range(0, len(items), per_page)] or [[]]
    pages = []
    for n, chunk in enumerate(chunks, 1):
        embed = discord.Embed(
            title=title, colour=discord.Colour.blurple(),
            description="\n".join(list_line(s) for s in chunk) or "Nothing here yet.",
        )
        footer = "Open one with /recipe show <id>"
        embed.set_footer(text=f"Page {n}/{len(chunks)} · {footer}" if len(chunks) > 1 else footer)
        pages.append(embed)
    return pages
