"""ExtractionBackend interface plus the validate-and-retry logic both backends share."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from ...models import Recipe
from .. import PipelineError
from ..download import VideoMeta

log = logging.getLogger(__name__)


class ExtractionError(PipelineError):
    """Claude couldn't produce a valid recipe. The message is shown to the user."""


@dataclass
class Attempt:
    """One raw backend call: output to validate plus whatever usage the backend reports."""

    output: str | dict[str, Any]
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    raw: str = ""


@dataclass
class ExtractionResult:
    recipe: Recipe
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None
    raw: str  # last raw output, for logging


class ExtractionBackend(Protocol):
    name: str

    async def extract(
        self, caption: str, transcript: str | None, frames: list[Path], metadata: VideoMeta, job_dir: Path,
    ) -> ExtractionResult: ...


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def parse_recipe(output: str | dict[str, Any]) -> Recipe:
    """Validate backend output. Raises ValueError (JSON) or ValidationError (schema)."""
    if isinstance(output, str):
        text = _FENCE.sub("", output.strip())
        # Tolerate a sentence before/after the object.
        start, end = text.find("{"), text.rfind("}")
        output = json.loads(text[start : end + 1] if start != -1 else text)
    return Recipe.model_validate(output)


def _add(a: int | float | None, b: int | float | None) -> int | float | None:
    return b if a is None else a if b is None else a + b


async def extract_with_retry(call: Callable[[str | None], Awaitable[Attempt]]) -> ExtractionResult:
    """Call, validate, and on failure call once more with the error included.

    ``call`` receives None on the first try and the validation error text on the retry.
    """
    error: str | None = None
    tokens_in = tokens_out = cost = None
    for _ in range(2):
        attempt = await call(error)
        tokens_in = _add(tokens_in, attempt.input_tokens)
        tokens_out = _add(tokens_out, attempt.output_tokens)
        cost = _add(cost, attempt.cost_usd)
        try:
            recipe = parse_recipe(attempt.output)
        except (ValueError, ValidationError) as exc:  # JSONDecodeError is a ValueError
            error = str(exc)[:2000]
            log.warning("Invalid recipe output (%s). Raw: %.500s", error, attempt.raw or attempt.output)
            continue
        return ExtractionResult(recipe, tokens_in, tokens_out, cost, attempt.raw)
    raise ExtractionError("Claude's answer didn't come back as a valid recipe, even after a retry.")


def retry_note(error: str | None) -> str:
    if not error:
        return ""
    return (
        "\n\nYour previous answer failed validation with this error:\n"
        f"{error}\nReply again with ONLY the corrected JSON object."
    )
