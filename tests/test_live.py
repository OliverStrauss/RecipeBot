"""Real Claude calls, one per backend. Run with: RUN_LIVE_TESTS=1 pytest tests/test_live.py

The CLI test bills the signed-in subscription; the API test needs ANTHROPIC_API_KEY.
"""

import json
import os
import shutil
from pathlib import Path

import pytest

from recipe_bot.pipeline.download import VideoMeta
from recipe_bot.pipeline.extract.api_backend import ApiBackend
from recipe_bot.pipeline.extract.cli_backend import CliBackend

pytestmark = pytest.mark.skipif(os.environ.get("RUN_LIVE_TESTS") != "1", reason="set RUN_LIVE_TESTS=1")

SAMPLES = json.loads((Path(__file__).parent / "fixtures" / "samples.json").read_text())
META = VideoMeta("instagram", "https://www.instagram.com/reel/C_y9HUQyh9d/", "", "chacekitchen", None, 69)


def check(result):
    recipe = result.recipe
    assert recipe.is_recipe
    assert "soup" in recipe.title.lower()
    assert any("carrot" in i.item.lower() for i in recipe.ingredients)
    assert len(recipe.steps) >= 3


@pytest.mark.skipif(shutil.which(os.environ.get("CLAUDE_CLI_PATH", "claude")) is None, reason="claude CLI not installed")
async def test_cli_backend_live(tmp_path):
    s = SAMPLES["narrated"]
    backend = CliBackend(os.environ.get("CLAUDE_CLI_PATH", "claude"), os.environ.get("CLAUDE_MODEL") or None, 180)
    check(await backend.extract(s["caption"], s["transcript"], [], META, tmp_path))


@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set")
async def test_api_backend_live(tmp_path):
    s = SAMPLES["narrated"]
    backend = ApiBackend(os.environ["ANTHROPIC_API_KEY"], os.environ.get("CLAUDE_MODEL") or None)
    check(await backend.extract(s["caption"], s["transcript"], [], META, tmp_path))
