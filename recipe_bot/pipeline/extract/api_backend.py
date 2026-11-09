"""api backend: the Anthropic SDK with an API key (pay-per-use).

PLAN.md asked for a forced `save_recipe` tool call. Current models (Opus 5.5,
Sonnet 5.5) reject forced tool_choice with a 400, so this uses structured
outputs instead: `messages.parse(output_format=Recipe)` constrains the reply to
the Recipe JSON schema, which is the same guarantee.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

import anthropic

from ...models import Recipe
from ..download import VideoMeta
from ..media import frame_seconds
from .base import Attempt, ExtractionError, ExtractionResult, extract_with_retry, retry_note
from .prompt import SYSTEM_PROMPT, build_context

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"


class ApiBackend:
    name = "api"

    def __init__(self, api_key: str, model: str | None, client: anthropic.AsyncAnthropic | None = None):
        self.client = client or anthropic.AsyncAnthropic(api_key=api_key)
        self.model = model or DEFAULT_MODEL

    async def extract(
        self, caption: str, transcript: str | None, frames: list[Path], metadata: VideoMeta, job_dir: Path,
    ) -> ExtractionResult:
        content: list[dict] = [{"type": "text", "text": build_context(caption, transcript, frames, metadata)}]
        for frame in frames:
            content.append({"type": "text", "text": f"{frame.name} (at {frame_seconds(frame)}s):"})
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg",
                           "data": base64.standard_b64encode(frame.read_bytes()).decode()},
            })
        content.append({"type": "text", "text": "Write the recipe."})
        return await extract_with_retry(lambda error: self._call(content, error))

    async def _call(self, content: list[dict], error: str | None) -> Attempt:
        if error:
            content = [*content, {"type": "text", "text": retry_note(error)}]
        try:
            response = await self.client.beta.messages.parse(
                model=self.model,
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": content}],
                output_format=Recipe,
                # If a safety classifier declines, re-run on Anthropic's recommended fallback model.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.AuthenticationError:
            raise ExtractionError("The bot's ANTHROPIC_API_KEY was rejected.") from None
        except anthropic.RateLimitError:
            raise ExtractionError("Claude's API is rate-limiting the bot right now. Try again in a bit.") from None
        except anthropic.APIStatusError as exc:
            log.error("Anthropic API error %s: %s", exc.status_code, exc.message)
            raise ExtractionError("The Claude API returned an error (details in the bot's log).") from None
        except anthropic.APIConnectionError as exc:
            log.error("Couldn't reach the Anthropic API: %s", exc)
            raise ExtractionError("Couldn't reach the Claude API.") from None

        usage = response.usage
        log.info("API %s: stop=%s in=%s out=%s", self.model, response.stop_reason,
                 usage.input_tokens, usage.output_tokens)
        if response.stop_reason == "refusal":
            raise ExtractionError("Claude declined to process this video.")
        text = "".join(b.text for b in response.content if b.type == "text")
        tokens_in = (usage.input_tokens or 0) + (usage.cache_creation_input_tokens or 0) + (
            usage.cache_read_input_tokens or 0)
        return Attempt(output=text, input_tokens=tokens_in, output_tokens=usage.output_tokens, raw=text)
