"""yt-dlp wrapper: URL -> (video file, metadata). Blocking; call via asyncio.to_thread."""

from __future__ import annotations

import json
import logging
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import yt_dlp
from yt_dlp.version import __version__ as YTDLP_VERSION

from . import PipelineError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class VideoMeta:
    platform: str
    url: str  # canonical page URL reported by yt-dlp
    caption: str
    creator: str | None  # @handle without the @
    title: str | None
    duration: float | None  # seconds


def _creator(info: dict, platform: str) -> str | None:
    # TikTok: uploader is the @handle. Instagram: channel is the @handle, uploader is the full name.
    keys = ("uploader", "channel") if platform == "tiktok" else ("channel", "uploader_id", "uploader")
    return next((str(info[k]) for k in keys if info.get(k)), None)


def download(url: str, platform: str, job_dir: Path, *, max_seconds: int, cookies: Path | None = None) -> tuple[Path, VideoMeta]:
    """Download ``url`` into ``job_dir``. Raises PipelineError with a user-facing message."""
    opts = {
        "outtmpl": str(job_dir / "video.%(ext)s"),
        # Small is plenty for transcription and 768px frames.
        "format": "best[height<=720]/bestvideo[height<=720]+bestaudio/best",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "playlist_items": "1",  # Instagram carousels: first item only
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }
    if cookies and platform == "instagram":
        opts["cookiefile"] = str(cookies)

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info.get("entries"):
                info = next(e for e in info["entries"] if e)
            duration = info.get("duration")
            if duration and duration > max_seconds:
                raise PipelineError(
                    f"That video is {duration / 60:.0f} min long; the limit is {max_seconds / 60:.0f} min."
                )
            info = ydl.process_ie_result(info, download=True)
    except yt_dlp.utils.DownloadError as exc:
        log.warning("yt-dlp failed for %s: %s", url, exc)
        text = str(exc).lower()
        if platform == "instagram" and ("login" in text or "cookie" in text or "rate-limit" in text):
            raise PipelineError(
                "Instagram wants a login for this one. The bot owner can set IG_COOKIES_PATH "
                "(see the README)."
            ) from exc
        if "private" in text or "unavailable" in text or "not available" in text:
            raise PipelineError("That video is private or no longer available.") from exc
        raise PipelineError(
            "Couldn't download that video. The site may have changed; the bot owner may need to "
            "update yt-dlp (`pip install -U yt-dlp`)."
        ) from exc

    video = next(job_dir.glob("video.*"), None)
    if video is None:
        raise PipelineError("The download finished but no video file showed up.")
    meta = VideoMeta(
        platform=platform,
        url=info.get("webpage_url") or url,
        caption=(info.get("description") or "").strip(),
        creator=_creator(info, platform),
        title=info.get("title"),
        duration=info.get("duration"),
    )
    return video, meta


def check_ytdlp_version() -> str | None:
    """Warning text if a newer yt-dlp is on PyPI, else None. Blocking; never raises."""
    try:
        with urllib.request.urlopen("https://pypi.org/pypi/yt-dlp/json", timeout=10) as resp:
            latest = json.load(resp)["info"]["version"]
    except Exception as exc:  # offline, PyPI down: not worth failing startup over
        log.debug("yt-dlp version check skipped: %s", exc)
        return None
    # Versions are dates (2026.10.26), so comparing as int tuples is enough.
    def as_tuple(v: str) -> tuple[int, ...]:
        return tuple(int(p) for p in v.split(".") if p.isdigit())
    if as_tuple(latest) > as_tuple(YTDLP_VERSION):
        return (
            f"yt-dlp {YTDLP_VERSION} is outdated (latest {latest}). Downloads break when sites "
            "change; run `pip install -U yt-dlp` and restart."
        )
    return None
