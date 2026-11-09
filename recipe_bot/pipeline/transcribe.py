"""faster-whisper transcription. The model loads once (first use) and is reused.

Blocking; call via asyncio.to_thread.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

log = logging.getLogger(__name__)

_lock = threading.Lock()
_models: dict[str, object] = {}


def _model(name: str):
    with _lock:
        if name not in _models:
            from faster_whisper import WhisperModel  # slow import; keep it off bot startup

            log.info("Loading whisper model %r (first run downloads it)", name)
            _models[name] = WhisperModel(name, device="cpu", compute_type="int8")
        return _models[name]


def transcribe(wav: Path, model_name: str = "base") -> str | None:
    """Transcript text, or None when there's no speech (music-only videos)."""
    # vad_filter skips non-speech, which also stops whisper "hallucinating" lyrics/outros over music.
    segments, _info = _model(model_name).transcribe(str(wav), vad_filter=True)
    text = " ".join(s.text.strip() for s in segments).strip()
    return text or None
