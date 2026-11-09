import asyncio
import json
from pathlib import Path

import pytest

from recipe_bot.pipeline.download import VideoMeta
from recipe_bot.pipeline.extract import ExtractionError
from recipe_bot.pipeline.extract import cli_backend
from recipe_bot.pipeline.extract.cli_backend import CliBackend

FIXTURES = Path(__file__).parent / "fixtures"
RECORDED = (FIXTURES / "cli_output.json").read_bytes()
META = VideoMeta("instagram", "https://www.instagram.com/reel/C_y9HUQyh9d/", "caption", "chacekitchen", None, 69)


class FakeProc:
    def __init__(self, stdout: bytes, delay: float = 0):
        self.stdout, self.delay, self.returncode, self.killed = stdout, delay, 0, False

    async def communicate(self, input=None):
        self.input = input.decode()
        await asyncio.sleep(self.delay)
        return self.stdout, b""

    def kill(self):
        self.killed = True

    async def wait(self):
        return self.returncode


@pytest.fixture
def fake_exec(monkeypatch):
    """Queue up FakeProcs; records each call's args and kwargs."""
    calls, procs = [], []

    async def exec_(*args, **kwargs):
        proc = procs.pop(0)
        calls.append((args, kwargs, proc))
        return proc

    monkeypatch.setattr(cli_backend.asyncio, "create_subprocess_exec", exec_)
    return calls, procs


def frames_in(tmp_path):
    frames = [tmp_path / "frame_0000s.jpg", tmp_path / "frame_0004s.jpg"]
    for f in frames:
        f.write_bytes(b"jpg")
    return frames


def wrapper(result: str, **extra) -> bytes:
    return json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": result,
                       "usage": {"input_tokens": 10, "output_tokens": 5}, "total_cost_usd": 0.01, **extra}).encode()


async def test_recorded_output_parses(tmp_path, fake_exec):
    calls, procs = fake_exec
    procs.append(FakeProc(RECORDED))
    frames = frames_in(tmp_path)

    result = await CliBackend("claude", "sonnet", 60).extract("caption", "transcript", frames, META, tmp_path)

    assert result.recipe.title == "Marry Me Chicken Noodle Soup"
    assert result.input_tokens == 4 + 32996 + 3473
    assert result.output_tokens == 5701
    assert result.cost_usd == pytest.approx(0.1893493)

    args, kwargs, proc = calls[0]
    assert kwargs["cwd"] == tmp_path
    assert args[args.index("--tools") + 1] == "Read"
    assert args[args.index("--model") + 1] == "sonnet"
    assert "shell" not in kwargs
    assert "context.md, frame_0000s.jpg, frame_0004s.jpg" in proc.input
    context = (tmp_path / "context.md").read_text()
    assert "caption" in context and "transcript" in context and "frame_0004s.jpg: at 0:04" in context


async def test_no_model_flag_by_default(tmp_path, fake_exec):
    calls, procs = fake_exec
    procs.append(FakeProc(RECORDED))
    await CliBackend("claude", None, 60).extract("c", None, [], META, tmp_path)
    assert "--model" not in calls[0][0]
    assert "(no speech detected)" in (tmp_path / "context.md").read_text()


async def test_retries_once_with_validation_error(tmp_path, fake_exec):
    calls, procs = fake_exec
    good = json.loads(RECORDED)["result"]
    procs += [FakeProc(wrapper('{"title": "half a recipe"}')), FakeProc(wrapper(good))]

    result = await CliBackend("claude", None, 60).extract("c", None, [], META, tmp_path)

    assert result.recipe.title == "Marry Me Chicken Noodle Soup"
    assert "failed validation" in calls[1][2].input and "ingredients" in calls[1][2].input
    assert result.input_tokens == 20  # usage from both attempts


async def test_fails_after_second_invalid_answer(tmp_path, fake_exec):
    _, procs = fake_exec
    procs += [FakeProc(wrapper("not json")), FakeProc(wrapper("still not json"))]
    with pytest.raises(ExtractionError, match="even after a retry"):
        await CliBackend("claude", None, 60).extract("c", None, [], META, tmp_path)


async def test_cli_error_result(tmp_path, fake_exec):
    _, procs = fake_exec
    procs.append(FakeProc(wrapper("", is_error=True, subtype="error_max_turns")))
    with pytest.raises(ExtractionError, match="turns"):
        await CliBackend("claude", None, 60).extract("c", None, [], META, tmp_path)


async def test_timeout_kills_process(tmp_path, fake_exec):
    calls, procs = fake_exec
    procs.append(FakeProc(RECORDED, delay=5))
    with pytest.raises(ExtractionError, match="longer than"):
        await CliBackend("claude", None, 0.05).extract("c", None, [], META, tmp_path)
    assert calls[0][2].killed
