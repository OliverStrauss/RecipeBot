from pathlib import Path

import pytest
from dotenv import dotenv_values

from recipe_bot.config import Config, ConfigError, load_config

ROOT = Path(__file__).resolve().parent.parent


def test_minimal_env_uses_defaults():
    config = load_config({"DISCORD_TOKEN": "abc"})
    assert config.discord_token == "abc"
    assert config.claude_backend == "claude_cli"
    assert config.claude_model is None
    assert config.dev_guild_id is None
    assert config.default_daily_limit == 15
    assert config.worker_concurrency == 1
    assert config.db_path == Path("./data/recipes.db")
    assert config.log_level == "INFO"


def test_blank_values_count_as_unset():
    config = load_config({"DISCORD_TOKEN": "abc", "CLAUDE_MODEL": "  ", "DEV_GUILD_ID": ""})
    assert config.claude_model is None
    assert config.dev_guild_id is None


def test_values_are_parsed():
    config = load_config({
        "DISCORD_TOKEN": "abc",
        "CLAUDE_BACKEND": "API",
        "CLAUDE_MODEL": "claude-sonnet-5-5",
        "DEV_GUILD_ID": "123456789012345678",
        "MAX_FRAMES": "8",
        "LOG_LEVEL": "debug",
    })
    assert config.claude_backend == "api"
    assert config.claude_model == "claude-sonnet-5-5"
    assert config.dev_guild_id == 123456789012345678
    assert config.max_frames == 8
    assert config.log_level == "DEBUG"


def test_missing_token_fails():
    with pytest.raises(ConfigError) as err:
        load_config({})
    assert any("DISCORD_TOKEN" in p for p in err.value.problems)


def test_all_problems_reported_at_once():
    with pytest.raises(ConfigError) as err:
        load_config({
            "CLAUDE_BACKEND": "gpt",
            "MAX_FRAMES": "lots",
            "WORKER_CONCURRENCY": "0",
            "DEV_GUILD_ID": "my-server",
            "LOG_LEVEL": "loud",
        })
    text = "\n".join(err.value.problems)
    for name in ("DISCORD_TOKEN", "CLAUDE_BACKEND", "MAX_FRAMES", "WORKER_CONCURRENCY", "DEV_GUILD_ID", "LOG_LEVEL"):
        assert name in text
    assert len(err.value.problems) == 6


def test_secrets_hidden_from_repr():
    config = load_config({
        "DISCORD_TOKEN": "discord-secret",
        "CLAUDE_CODE_OAUTH_TOKEN": "oauth-secret",
        "ANTHROPIC_API_KEY": "api-secret",
    })
    text = repr(config)
    assert "discord-secret" not in text
    assert "oauth-secret" not in text
    assert "api-secret" not in text


def test_warns_when_cli_backend_has_api_key():
    config = load_config({"DISCORD_TOKEN": "abc", "ANTHROPIC_API_KEY": "sk", "CLAUDE_CODE_OAUTH_TOKEN": "t"})
    warnings = config.warnings()
    assert len(warnings) == 1
    assert "ANTHROPIC_API_KEY" in warnings[0]


def test_no_warnings_for_clean_cli_setup():
    config = load_config({"DISCORD_TOKEN": "abc", "CLAUDE_CODE_OAUTH_TOKEN": "t"})
    assert config.warnings() == []


def test_warns_when_api_backend_has_no_key():
    config = load_config({"DISCORD_TOKEN": "abc", "CLAUDE_BACKEND": "api"})
    assert any("ANTHROPIC_API_KEY" in w for w in config.warnings())


def test_env_example_loads_and_covers_every_setting():
    """.env.example must stay in sync with Config: every field documented, every key known."""
    values = {k: v or "" for k, v in dotenv_values(ROOT / ".env.example").items()}
    values["DISCORD_TOKEN"] = "abc"
    config = load_config(values)
    assert config.claude_backend == "claude_cli"
    assert config.claude_model is None  # inline comments must not leak into values

    documented = {k.lower() for k in values}
    fields = set(Config.__dataclass_fields__)
    assert documented == fields
