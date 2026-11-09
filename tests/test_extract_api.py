import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from recipe_bot.models import Recipe
from recipe_bot.pipeline.download import VideoMeta
from recipe_bot.pipeline.extract import ExtractionError
from recipe_bot.pipeline.extract.api_backend import DEFAULT_MODEL, ApiBackend

RECIPE_JSON = json.loads(json.loads((Path(__file__).parent / "fixtures" / "cli_output.json").read_text())["result"]
                         .removeprefix("```json\n").removesuffix("\n```"))
META = VideoMeta("tiktok", "https://www.tiktok.com/@a/video/1", "caption", "a", None, 30)


def response(text: str, stop_reason: str = "end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=100, output_tokens=50,
                              cache_creation_input_tokens=0, cache_read_input_tokens=None),
    )


def backend(*responses, model=None):
    client = MagicMock()
    client.beta.messages.parse = AsyncMock(side_effect=list(responses))
    return ApiBackend("sk-test", model, client=client), client.beta.messages.parse


async def test_sends_text_and_frames_with_recipe_schema(tmp_path):
    frames = [tmp_path / "frame_0000s.jpg", tmp_path / "frame_0006s.jpg"]
    for f in frames:
        f.write_bytes(b"\xff\xd8jpg")
    api, parse = backend(response(json.dumps(RECIPE_JSON)))

    result = await api.extract("the caption", "the transcript", frames, META, tmp_path)

    assert result.recipe.title == RECIPE_JSON["title"]
    assert (result.input_tokens, result.output_tokens) == (100, 50)
    kwargs = parse.await_args.kwargs
    assert kwargs["model"] == DEFAULT_MODEL
    assert kwargs["output_format"] is Recipe
    content = kwargs["messages"][0]["content"]
    assert "the caption" in content[0]["text"] and "the transcript" in content[0]["text"]
    images = [b for b in content if b["type"] == "image"]
    assert len(images) == 2 and images[0]["source"]["media_type"] == "image/jpeg"
    assert any(b["type"] == "text" and "frame_0006s.jpg (at 6s)" in b["text"] for b in content)


async def test_model_override_and_retry(tmp_path):
    api, parse = backend(response('{"title": "oops"}'), response(json.dumps(RECIPE_JSON)), model="claude-sonnet-5-5")

    result = await api.extract("c", None, [], META, tmp_path)

    assert parse.await_count == 2
    assert parse.await_args.kwargs["model"] == "claude-sonnet-5-5"
    assert "failed validation" in parse.await_args.kwargs["messages"][0]["content"][-1]["text"]
    assert result.input_tokens == 200


async def test_refusal(tmp_path):
    api, _ = backend(response("", stop_reason="refusal"))
    with pytest.raises(ExtractionError, match="declined"):
        await api.extract("c", None, [], META, tmp_path)
