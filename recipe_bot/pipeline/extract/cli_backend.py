"""claude_cli backend: Claude Code in headless mode (`claude -p`), billed to the owner's subscription."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path

from ...models import Recipe
from ..download import VideoMeta
from .base import Attempt, ExtractionError, ExtractionResult, extract_with_retry, retry_note
from .prompt import SYSTEM_PROMPT, build_context

log = logging.getLogger(__name__)

# --max-turns counts model round trips: 2 when Claude batches the Reads as asked
# (reads, then answer). The JSON's num_turns counts each tool result, so it reads ~22.
MAX_TURNS = 5


class CliError(Exception):
    """`claude` is missing or not signed in (startup check)."""


def check_cli(cli_path: str) -> str:
    """Return the CLI version, or raise CliError with a fix-it message. Blocking."""
    try:
        version = subprocess.run(
            [cli_path, "--version"], capture_output=True, text=True, timeout=30, check=True,
        ).stdout.strip()
        status = subprocess.run(
            [cli_path, "auth", "status"], capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError:
        raise CliError(
            f"Claude Code CLI not found ({cli_path!r}). Install it (see README) or set CLAUDE_CLI_PATH."
        ) from None
    except (subprocess.SubprocessError, OSError) as exc:
        raise CliError(f"`{cli_path} --version` failed: {exc}") from None
    try:
        logged_in = json.loads(status.stdout).get("loggedIn", False)
    except ValueError:
        logged_in = status.returncode == 0
    if not logged_in:
        raise CliError(
            "Claude Code CLI is not signed in. Run `claude setup-token` on your computer and put the "
            "token in .env as CLAUDE_CODE_OAUTH_TOKEN (or run `claude` once on this machine to log in)."
        )
    return version


class CliBackend:
    name = "claude_cli"

    def __init__(self, cli_path: str, model: str | None, timeout: int):
        self.cli_path = cli_path
        self.model = model
        self.timeout = timeout

    def _args(self) -> list[str]:
        args = [
            self.cli_path, "-p",
            "--output-format", "json",
            "--system-prompt", SYSTEM_PROMPT,
            # Read is the only tool that exists in the session: no Bash, no Edit, no web.
            "--tools", "Read", "--allowedTools", "Read",
            # Captions are untrusted. Without this, an injected "read ../.env" works (tested);
            # restricted mode confines Read to the job folder.
            "--restricted",
            "--max-turns", str(MAX_TURNS),
            "--no-session-persistence",
            # Ignore the host's hooks, plugins, CLAUDE.md and MCP servers (matters on a dev Mac).
            "--safe-mode",
        ]
        if self.model:
            args += ["--model", self.model]
        return args

    async def extract(
        self, caption: str, transcript: str | None, frames: list[Path], metadata: VideoMeta, job_dir: Path,
    ) -> ExtractionResult:
        (job_dir / "context.md").write_text(build_context(caption, transcript, frames, metadata))
        files = ["context.md", *(f.name for f in frames)]
        # Naming every file lets Claude fire all the Reads in its first turn instead of
        # reading context.md first to learn the frame names.
        prompt = (
            f"Read these files in this folder, all at once with parallel Read calls in a single "
            f"message: {', '.join(files)}.\n"
            "Then respond with ONLY a JSON object matching this schema, no prose, no code fences:\n"
            f"{json.dumps(Recipe.model_json_schema())}"
        )
        return await extract_with_retry(lambda error: self._run(prompt + retry_note(error), job_dir))

    async def _run(self, prompt: str, cwd: Path) -> Attempt:
        proc = await asyncio.create_subprocess_exec(
            *self._args(), cwd=cwd,
            env={k: v for k, v in os.environ.items() if k != "DISCORD_TOKEN"},  # Claude never needs it
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(prompt.encode()), self.timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise ExtractionError(f"Claude took longer than {self.timeout}s on this one.") from None

        try:
            data = json.loads(out)
        except ValueError:
            log.error("claude -p exited %s with non-JSON output. stdout: %.1000s stderr: %.1000s",
                      proc.returncode, out.decode(errors="replace"), err.decode(errors="replace"))
            raise ExtractionError("The Claude CLI failed (details in the bot's log).") from None

        usage = data.get("usage") or {}
        log.info(
            "claude -p: %s, %s turns, cost $%s, usage %s",
            data.get("subtype"), data.get("num_turns"), data.get("total_cost_usd"),
            {k: usage.get(k) for k in ("input_tokens", "cache_creation_input_tokens",
                                       "cache_read_input_tokens", "output_tokens")},
        )
        if data.get("is_error") or data.get("subtype") != "success":
            log.error("claude -p error result: %.2000s", out.decode(errors="replace"))
            if data.get("subtype") == "error_max_turns":
                raise ExtractionError("Claude ran out of turns reading the video frames.")
            raise ExtractionError("The Claude CLI returned an error (details in the bot's log).")

        tokens_in = sum(usage.get(k) or 0 for k in (
            "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
        return Attempt(
            output=data.get("result") or "",
            input_tokens=tokens_in or None,
            output_tokens=usage.get("output_tokens"),
            cost_usd=data.get("total_cost_usd"),
            raw=data.get("result") or "",
        )
