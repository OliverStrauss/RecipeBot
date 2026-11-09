"""Video -> recipe pipeline. Blocking work (yt-dlp, whisper) runs in threads."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import Config
    from .download import VideoMeta

log = logging.getLogger(__name__)


class PipelineError(Exception):
    """A failure with a short, user-facing message (shown in Discord)."""


@dataclass
class Media:
    video: Path
    meta: VideoMeta
    transcript: str | None
    frames: list[Path]


async def fetch(url: str, platform: str, job_dir: Path, config: Config) -> tuple[Path, VideoMeta]:
    from .download import download
    from .media import probe_duration

    video, meta = await asyncio.to_thread(
        download, url, platform, job_dir,
        max_seconds=config.max_video_seconds, cookies=config.ig_cookies_path,
    )
    if meta.duration is None:  # Instagram: only known once the file is here
        meta = replace(meta, duration=await probe_duration(video))
        if meta.duration and meta.duration > config.max_video_seconds:
            raise PipelineError(
                f"That video is {meta.duration / 60:.0f} min long; "
                f"the limit is {config.max_video_seconds / 60:.0f} min."
            )
    return video, meta


async def prepare(video: Path, meta: VideoMeta, job_dir: Path, config: Config) -> Media:
    """Audio -> transcript, plus sampled frames, all into ``job_dir``."""
    from .media import extract_audio, extract_frames
    from .transcribe import transcribe

    started = time.monotonic()
    wav = await extract_audio(video, job_dir / "audio.wav")
    transcript = await asyncio.to_thread(transcribe, wav, config.whisper_model) if wav else None
    transcribed = time.monotonic()
    frames = await extract_frames(
        video, job_dir, interval=config.frame_interval_seconds,
        max_frames=config.max_frames, duration=meta.duration,
    )
    log.info(
        "Prepared %s: %.0fs video, transcript %s chars in %.1fs, %d frames in %.1fs",
        meta.url, meta.duration or 0, len(transcript or ""), transcribed - started,
        len(frames), time.monotonic() - transcribed,
    )
    return Media(video, meta, transcript, frames)
