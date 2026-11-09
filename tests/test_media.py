"""ffmpeg integration: a tiny video is generated on the fly (no binary fixture to commit)."""

import shutil
import subprocess

import pytest

from recipe_bot.pipeline.media import extract_audio, extract_frames, frame_seconds, probe_duration

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def make_video(path, *, audio: bool):
    # 4s red, 6s test pattern (changes every second), 4s blue = 14s.
    cmd = [
        "ffmpeg", "-v", "error", "-y",
        "-f", "lavfi", "-i", "color=c=red:s=320x240:d=4",
        "-f", "lavfi", "-i", "testsrc=s=320x240:d=6",
        "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=4",
    ]
    if audio:
        cmd += ["-f", "lavfi", "-i", "sine=frequency=440:duration=14"]
    cmd += ["-filter_complex", "[0][1][2]concat=n=3:v=1:a=0,format=yuv420p[v]", "-map", "[v]"]
    if audio:
        cmd += ["-map", "3:a", "-shortest"]
    cmd.append(str(path))
    subprocess.run(cmd, check=True)
    return path


async def test_frames_sampled_deduped_and_named_by_time(tmp_path):
    video = make_video(tmp_path / "v.mp4", audio=False)
    frames = await extract_frames(video, tmp_path, interval=2, max_frames=20, duration=14)
    # Samples at 0,2,4,...,12s. The repeat red (2s) and repeat blue (12s) are near-duplicates.
    assert [frame_seconds(f) for f in frames] == [0, 4, 6, 8, 10]
    assert all(f.exists() and f.name.startswith("frame_") for f in frames)


async def test_long_video_spreads_frames(tmp_path):
    video = make_video(tmp_path / "v.mp4", audio=False)
    frames = await extract_frames(video, tmp_path, interval=1, max_frames=4, duration=14)
    assert len(frames) <= 4
    assert max(frame_seconds(f) for f in frames) >= 7  # not just the first 4 seconds


async def test_audio_extracted(tmp_path):
    video = make_video(tmp_path / "v.mp4", audio=True)
    assert round(await probe_duration(video)) == 14
    wav = await extract_audio(video, tmp_path / "a.wav")
    assert wav is not None and wav.stat().st_size > 16000  # ~14s of 16 kHz 16-bit mono


async def test_no_audio_track_returns_none(tmp_path):
    video = make_video(tmp_path / "v.mp4", audio=False)
    assert await extract_audio(video, tmp_path / "a.wav") is None
