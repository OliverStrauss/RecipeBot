"""System prompt and input assembly, shared by both backends."""

from __future__ import annotations

from pathlib import Path

from ..download import VideoMeta
from ..media import frame_seconds

SYSTEM_PROMPT = """\
You turn short cooking videos (TikTok, Instagram Reels) into clean, written recipes.

You get up to three sources: the post's caption, a transcript of the audio, and frames \
sampled from the video. Combine all three. On-screen text and the caption usually have the \
most precise amounts; the transcript usually has the order and technique. Instagram captions \
often hold the full recipe, so weigh them heavily.

Rules:
- When an amount isn't given anywhere, estimate a sensible one for the stated servings and set \
"estimated": true on that ingredient. Amounts the video or caption states are "estimated": false.
- Never invent ingredients that aren't shown or mentioned.
- Use US units by default. Keep metric if that's what the creator used.
- Write steps as clear, standalone instructions (never "like I said earlier").
- Keep creator tips worth remembering in "tips". Add short lowercase tags (main ingredient, \
cuisine, method like "air fryer", diet like "vegetarian", course like "dessert").
- "confidence": "high" when amounts and steps are all stated, "medium" when you filled real \
gaps, "low" when most of it is guesswork. Explain anything below high in "confidence_note".
- If the recipe is gated ("comment RECIPE and I'll DM you"), do your best from the visuals, set \
"confidence": "low", and say so in "confidence_note".
- If the video isn't a recipe at all, set "is_recipe": false and keep everything else minimal.
"""


def build_context(caption: str, transcript: str | None, frames: list[Path], meta: VideoMeta) -> str:
    """Markdown with everything except the images themselves.

    The CLI backend writes this to context.md; the API backend sends it as the text block.
    """
    lines = [
        "# Video",
        f"- Platform: {meta.platform}",
        f"- URL: {meta.url}",
        f"- Creator: @{meta.creator}" if meta.creator else "- Creator: unknown",
    ]
    if meta.duration:
        lines.append(f"- Length: {meta.duration:.0f} seconds")
    if meta.title and meta.title.strip() not in caption:
        lines.append(f"- Title: {meta.title.strip()}")
    lines += ["", "# Caption", caption or "(no caption)", "", "# Transcript", transcript or "(no speech detected)"]
    if frames:
        lines += ["", "# Frames", "Sampled from the video (near-duplicates removed):"]
        lines += [f"- {f.name}: at {_mmss(frame_seconds(f))}" for f in frames]
    return "\n".join(lines) + "\n"


def _mmss(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"
