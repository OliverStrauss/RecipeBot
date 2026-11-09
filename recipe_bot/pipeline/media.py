"""ffmpeg: audio for transcription and sampled frames for vision."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from . import PipelineError

log = logging.getLogger(__name__)


async def _ffmpeg(*args: str) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *args,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    return proc.returncode, err.decode(errors="replace").strip()


async def extract_audio(video: Path, out: Path) -> Path | None:
    """16 kHz mono wav, or None if the video has no usable audio track."""
    code, err = await _ffmpeg("-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(out))
    if code != 0 or not out.exists() or out.stat().st_size <= 44:  # 44 = empty wav header
        log.info("No audio extracted from %s: %s", video.name, err[-300:])
        return None
    return out


async def probe_duration(video: Path) -> float | None:
    """Seconds, from the file itself (Instagram metadata often lacks a duration)."""
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    try:
        return float(out)
    except ValueError:
        return None


def frame_seconds(path: Path) -> int:
    """frame_0012s.jpg -> 12"""
    return int(path.stem.removeprefix("frame_").removesuffix("s"))


async def extract_frames(
    video: Path, out_dir: Path, *, interval: float, max_frames: int,
    duration: float | None = None, width: int = 768,
) -> list[Path]:
    """Sample one frame every ``interval`` seconds, dropping near-duplicates.

    Long videos stretch the interval so the ``max_frames`` samples cover the whole
    video instead of only its first ``interval * max_frames`` seconds. Files are
    named by timestamp (frame_0012s.jpg) so both backends can label them.
    """
    if duration:
        interval = max(interval, duration / max_frames)
    raw_dir = out_dir / "raw_frames"
    raw_dir.mkdir(exist_ok=True)
    code, err = await _ffmpeg(
        "-i", str(video),
        # mpdecimate drops a sample that barely differs from the last kept one
        # (static shots); any strongly changed block, like new on-screen text, keeps it.
        "-vf", f"fps={1 / interval},mpdecimate,scale='min({width},iw)':-2",
        "-fps_mode", "vfr", "-frame_pts", "1", "-q:v", "3", "-frames:v", str(max_frames),
        str(raw_dir / "%05d.jpg"),
    )
    if code != 0:
        raise PipelineError(f"Couldn't read frames from the video ({err[-200:] or 'ffmpeg failed'}).")
    frames = []
    # With -frame_pts the file number is the sample index, so index * interval = timestamp.
    for raw in sorted(raw_dir.glob("*.jpg")):
        frame = out_dir / f"frame_{round(int(raw.stem) * interval):04d}s.jpg"
        raw.rename(frame)
        frames.append(frame)
    raw_dir.rmdir()
    return frames
