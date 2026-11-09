"""All Claude-specific code lives in this package; the rest of the bot only sees get_backend()."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import ExtractionBackend, ExtractionError, ExtractionResult

if TYPE_CHECKING:
    from ...config import Config

__all__ = ["ExtractionBackend", "ExtractionError", "ExtractionResult", "get_backend"]


def get_backend(config: Config) -> ExtractionBackend:
    if config.claude_backend == "api":
        from .api_backend import ApiBackend

        return ApiBackend(config.anthropic_api_key or "", config.claude_model)
    from .cli_backend import CliBackend

    return CliBackend(config.claude_cli_path, config.claude_model, config.claude_cli_timeout_seconds)
