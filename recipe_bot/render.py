"""Recipe -> Discord embed (with a .md fallback), -> Markdown, and -> HTML page."""

from __future__ import annotations

import io
from html import escape

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


def recipe_embed(saved: SavedRecipe, web_url: str | None = None) -> tuple[discord.Embed, discord.File | None]:
    """The full recipe as one embed, or a short embed plus a .md file when it won't fit.

    With ``web_url`` the title links to the recipe's web page; otherwise to the video.
    """
    recipe = saved.recipe
    head = [recipe.description, meta_line(recipe), warning_line(recipe)]
    embed = discord.Embed(
        title=recipe.title[:TITLE_LIMIT], colour=COLOURS[recipe.confidence],
        url=f"{web_url}/{saved.guild_id}/{saved.id}" if web_url else saved.source_url,
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


HTML_STYLE = """
:root { --bg: #fbf8f3; --card: #fff; --text: #2b2622; --muted: #7a6f66; --accent: #c0532b; --line: #e8e0d6; --warn-bg: #fff4d6; --warn: #6b4e00; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #1b1916; --card: #242120; --text: #ece6df; --muted: #a39a90; --accent: #e58a5f; --line: #3a3532; --warn-bg: #3d3115; --warn: #f2d27a; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font: 17px/1.6 system-ui, sans-serif; }
main { max-width: 60rem; margin: 2rem auto; padding: 2rem; background: var(--card); border-radius: 12px; }
h1, h2, h3 { font-family: Georgia, serif; line-height: 1.2; }
h1 { font-size: 2.2rem; margin: 0 0 .5rem; }
h2 { color: var(--accent); border-bottom: 2px solid var(--line); padding-bottom: .3rem; }
h3 { font-size: 1rem; text-transform: capitalize; color: var(--muted); margin: 1rem 0 .3rem; }
.meta { color: var(--muted); font-weight: 600; }
.warn { background: var(--warn-bg); color: var(--warn); padding: .6rem .9rem; border-radius: 8px; }
.cols { display: grid; grid-template-columns: 1fr 2fr; gap: 2.5rem; }
ul.ing { list-style: none; padding: 0; }
ul.ing li { padding: .25rem 0; border-bottom: 1px solid var(--line); }
input:checked + span { text-decoration: line-through; opacity: .5; }
ol.steps li { margin-bottom: 1rem; padding-left: .3rem; }
ol.steps li::marker { color: var(--accent); font-weight: 700; }
.time { color: var(--muted); font-size: .85em; white-space: nowrap; }
.tags span { display: inline-block; background: var(--line); border-radius: 99px; padding: .1rem .7rem; margin: .2rem; font-size: .85em; }
footer { color: var(--muted); font-size: .9em; margin-top: 2rem; }
a { color: var(--accent); }
@media (max-width: 700px) { main { margin: 0; padding: 1rem; border-radius: 0; } .cols { grid-template-columns: 1fr; gap: 0; } }
@media print { body { background: #fff; } main { margin: 0; } input { display: none; } }
"""


def recipe_html(saved: SavedRecipe) -> str:
    """The recipe as a standalone web page (no Claude call: a template over the saved JSON)."""
    recipe, e = saved.recipe, escape
    ingredients = []
    for group, items in _groups(recipe).items():
        if group:
            ingredients.append(f"<h3>{e(group)}</h3>")
        ingredients.append('<ul class="ing">' + "".join(
            f"<li><label><input type=checkbox> <span>{e(format_ingredient(i))}</span></label></li>" for i in items
        ) + "</ul>")
    steps = "".join(
        f"<li>{e(s.text)}" + (f' <span class="time">~{s.duration_minutes} min</span>' if s.duration_minutes else "")
        + "</li>" for s in recipe.steps
    )
    extras = ""
    if recipe.equipment:
        extras += "<h2>Equipment</h2><ul>" + "".join(f"<li>{e(x)}</li>" for x in recipe.equipment) + "</ul>"
    if recipe.tips:
        extras += "<h2>Tips</h2><ul>" + "".join(f"<li>{e(t)}</li>" for t in recipe.tips) + "</ul>"
    if recipe.tags:
        extras += '<p class="tags">' + "".join(f"<span>{e(t)}</span>" for t in recipe.tags) + "</p>"
    warning = f'<p class="warn">{e(warning_line(recipe))}</p>' if warning_line(recipe) else ""
    creator = f"@{saved.creator}" if saved.creator else "this video"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(recipe.title)}</title><style>{HTML_STYLE}</style></head>
<body><main>
<h1>{e(recipe.title)}</h1>
<p>{e(recipe.description)}</p>
<p class="meta">{e(meta_line(recipe))}</p>
{warning}
<div class="cols">
<section><h2>Ingredients</h2>{"".join(ingredients)}</section>
<section><h2>Steps</h2><ol class="steps">{steps}</ol>{extras}</section>
</div>
<footer>From <a href="{e(saved.source_url)}">{e(creator)}</a> on {e(PLATFORMS.get(saved.platform, saved.platform))}
· Recipe #{saved.id}</footer>
</main></body></html>
"""


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
