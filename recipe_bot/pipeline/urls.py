"""Find TikTok and Instagram video links in text and normalize them.

Normalized URLs are what dedupe keys on, so two shares of the same video
(different tracking params, m. vs www., /reels/ vs /reel/) map to one URL.
TikTok short links (vm.tiktok.com, /t/...) can't be resolved without a
request; they are kept as-is here and re-normalized after download from
yt-dlp's canonical ``webpage_url``.
"""

from __future__ import annotations

import re
from typing import NamedTuple


class VideoLink(NamedTuple):
    platform: str  # "tiktok" | "instagram"
    url: str  # normalized


_URL = re.compile(r"https?://[^\s<>|]+", re.IGNORECASE)

_TIKTOK_VIDEO = re.compile(
    r"^https?://(?:www\.|m\.)?tiktok\.com/@([\w.-]*)/video/(\d+)", re.IGNORECASE
)
_TIKTOK_SHORT = re.compile(
    r"^https?://(?:(?:vm|vt)\.tiktok\.com/(\w+)|(?:www\.|m\.)?tiktok\.com/t/(\w+))", re.IGNORECASE
)
# /reel/, /reels/, /p/, /tv/, optionally after a /username/ segment (newer share links).
_INSTAGRAM = re.compile(
    r"^https?://(?:www\.|m\.)?instagram\.com/(?:[\w.]+/)?(?:reels?|p|tv)/([\w-]+)", re.IGNORECASE
)


def normalize(url: str) -> VideoLink | None:
    """Return the canonical form of a TikTok/Instagram video URL, or None."""
    url = url.strip().rstrip(").,!>")
    if m := _TIKTOK_VIDEO.match(url):
        return VideoLink("tiktok", f"https://www.tiktok.com/@{m[1]}/video/{m[2]}")
    if m := _TIKTOK_SHORT.match(url):
        code = m[1] or m[2]
        return VideoLink("tiktok", f"https://vm.tiktok.com/{code}/" if m[1] else f"https://www.tiktok.com/t/{code}/")
    if m := _INSTAGRAM.match(url):
        return VideoLink("instagram", f"https://www.instagram.com/reel/{m[1]}/")
    return None


def find_links(text: str) -> list[VideoLink]:
    """All supported video links in ``text``, normalized, duplicates removed, in order."""
    seen: dict[str, VideoLink] = {}
    for raw in _URL.findall(text):
        if (link := normalize(raw)) and link.url not in seen:
            seen[link.url] = link
    return list(seen.values())
