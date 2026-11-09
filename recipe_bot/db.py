"""SQLite storage: schema and queries (PLAN.md section 7)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiosqlite

from .models import Recipe, SavedRecipe

# SCHEMA is the original layout; later changes go in MIGRATIONS so existing databases get them too.
SCHEMA = """
CREATE TABLE IF NOT EXISTS guilds (
  guild_id INTEGER PRIMARY KEY,
  recipe_channel_id INTEGER,
  daily_limit INTEGER,              -- NULL = DEFAULT_DAILY_LIMIT from config
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS recipes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  guild_id INTEGER NOT NULL,
  submitter_id INTEGER NOT NULL,
  source_url TEXT NOT NULL,         -- normalized
  platform TEXT NOT NULL,           -- 'tiktok' | 'instagram'
  creator TEXT,                     -- @handle, for credit
  title TEXT NOT NULL,
  tags TEXT,                        -- comma-separated
  recipe_json TEXT NOT NULL,
  confidence TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(guild_id, source_url)
);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  guild_id INTEGER, user_id INTEGER, source_url TEXT,
  status TEXT,                      -- queued|running|done|failed
  backend TEXT,                     -- claude_cli | api
  error TEXT,
  input_tokens INTEGER, output_tokens INTEGER,
  created_at TEXT, finished_at TEXT
);
CREATE INDEX IF NOT EXISTS jobs_user_day ON jobs(guild_id, user_id, created_at);
CREATE VIRTUAL TABLE IF NOT EXISTS recipe_search USING fts5(
  title, tags, ingredients, tokenize = 'porter unicode61 remove_diacritics 2'
);
"""

# Each entry runs once, in order. `PRAGMA user_version` counts how many have run. Append only.
MIGRATIONS = [
    "ALTER TABLE guilds ADD COLUMN cookbook_channel_id INTEGER",  # where finished recipes are posted
]

RECIPE_COLUMNS = "id, guild_id, submitter_id, source_url, platform, creator, recipe_json, created_at"


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _saved(row) -> SavedRecipe:
    return SavedRecipe(
        id=row[0], guild_id=row[1], submitter_id=row[2], source_url=row[3], platform=row[4],
        creator=row[5], recipe=Recipe.model_validate_json(row[6]), created_at=row[7],
    )


def fts_query(text: str) -> str | None:
    """User text -> safe FTS5 query: every word must match, as a prefix ("chick" finds chicken)."""
    words = re.findall(r"\w+", text.lower())
    return " ".join(f'"{w}"*' for w in words) or None


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = await aiosqlite.connect(self.path)
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.executescript(SCHEMA)
        (version,) = await self._one("PRAGMA user_version")
        for version, sql in enumerate(MIGRATIONS[version:], start=version + 1):
            await self.conn.execute(sql)
            await self.conn.execute(f"PRAGMA user_version={version}")
        # Jobs that were queued or running when the bot stopped will never finish.
        await self.conn.execute(
            "UPDATE jobs SET status='failed', error='bot restarted', finished_at=? "
            "WHERE status IN ('queued', 'running')", (now(),),
        )
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()
            self.conn = None

    async def _one(self, sql: str, args: tuple = ()):
        async with self.conn.execute(sql, args) as cur:
            return await cur.fetchone()

    async def _all(self, sql: str, args: tuple = ()) -> list:
        async with self.conn.execute(sql, args) as cur:
            return list(await cur.fetchall())

    # --- guild settings ---------------------------------------------------------------

    async def recipe_channel(self, guild_id: int) -> int | None:
        row = await self._one("SELECT recipe_channel_id FROM guilds WHERE guild_id=?", (guild_id,))
        return row[0] if row else None

    async def cookbook_channel(self, guild_id: int) -> int | None:
        row = await self._one("SELECT cookbook_channel_id FROM guilds WHERE guild_id=?", (guild_id,))
        return row[0] if row else None

    async def daily_limit(self, guild_id: int, default: int) -> int:
        row = await self._one("SELECT daily_limit FROM guilds WHERE guild_id=?", (guild_id,))
        return row[0] if row and row[0] is not None else default

    async def _set_guild(self, guild_id: int, column: str, value: int | None) -> None:
        await self.conn.execute(
            f"INSERT INTO guilds (guild_id, {column}, created_at) VALUES (?, ?, ?) "
            f"ON CONFLICT(guild_id) DO UPDATE SET {column}=excluded.{column}",
            (guild_id, value, now()),
        )
        await self.conn.commit()

    async def set_recipe_channel(self, guild_id: int, channel_id: int | None) -> None:
        await self._set_guild(guild_id, "recipe_channel_id", channel_id)

    async def set_cookbook_channel(self, guild_id: int, channel_id: int | None) -> None:
        await self._set_guild(guild_id, "cookbook_channel_id", channel_id)

    async def set_daily_limit(self, guild_id: int, limit: int) -> None:
        await self._set_guild(guild_id, "daily_limit", limit)

    # --- recipes ------------------------------------------------------------------------

    async def find_by_url(self, guild_id: int, url: str) -> SavedRecipe | None:
        row = await self._one(
            f"SELECT {RECIPE_COLUMNS} FROM recipes WHERE guild_id=? AND source_url=?", (guild_id, url))
        return _saved(row) if row else None

    async def get_recipe(self, guild_id: int, recipe_id: int) -> SavedRecipe | None:
        row = await self._one(
            f"SELECT {RECIPE_COLUMNS} FROM recipes WHERE guild_id=? AND id=?", (guild_id, recipe_id))
        return _saved(row) if row else None

    async def save_recipe(
        self, *, guild_id: int, submitter_id: int, source_url: str, platform: str,
        creator: str | None, recipe: Recipe,
    ) -> SavedRecipe:
        """Insert and index. If the URL is already saved in this guild, return the existing one."""
        cur = await self.conn.execute(
            "INSERT OR IGNORE INTO recipes (guild_id, submitter_id, source_url, platform, creator, title, "
            "tags, recipe_json, confidence, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (guild_id, submitter_id, source_url, platform, creator, recipe.title, ",".join(recipe.tags),
             recipe.model_dump_json(), recipe.confidence, now()),
        )
        if cur.rowcount:
            await self.conn.execute(
                "INSERT INTO recipe_search (rowid, title, tags, ingredients) VALUES (?, ?, ?, ?)",
                (cur.lastrowid, recipe.title, " ".join(recipe.tags),
                 " ".join(i.item for i in recipe.ingredients)),
            )
        await self.conn.commit()
        return await self.find_by_url(guild_id, source_url)

    async def delete_recipe(self, guild_id: int, recipe_id: int) -> bool:
        cur = await self.conn.execute("DELETE FROM recipes WHERE guild_id=? AND id=?", (guild_id, recipe_id))
        if cur.rowcount:
            await self.conn.execute("DELETE FROM recipe_search WHERE rowid=?", (recipe_id,))
        await self.conn.commit()
        return bool(cur.rowcount)

    async def recipes_by(self, guild_id: int, user_id: int, limit: int = 100) -> list[SavedRecipe]:
        rows = await self._all(
            f"SELECT {RECIPE_COLUMNS} FROM recipes WHERE guild_id=? AND submitter_id=? ORDER BY id DESC LIMIT ?",
            (guild_id, user_id, limit))
        return [_saved(r) for r in rows]

    async def recent(self, guild_id: int, limit: int = 10) -> list[SavedRecipe]:
        rows = await self._all(
            f"SELECT {RECIPE_COLUMNS} FROM recipes WHERE guild_id=? ORDER BY id DESC LIMIT ?", (guild_id, limit))
        return [_saved(r) for r in rows]

    async def random(self, guild_id: int, tag: str | None = None) -> SavedRecipe | None:
        if tag:
            # Tags are stored "a,b,c"; wrap in commas so "pie" doesn't match "pierogi".
            row = await self._one(
                f"SELECT {RECIPE_COLUMNS} FROM recipes WHERE guild_id=? "
                "AND ',' || lower(tags) || ',' LIKE ? ORDER BY random() LIMIT 1",
                (guild_id, f"%,{tag.strip().lower()},%"))
        else:
            row = await self._one(
                f"SELECT {RECIPE_COLUMNS} FROM recipes WHERE guild_id=? ORDER BY random() LIMIT 1", (guild_id,))
        return _saved(row) if row else None

    async def search(self, guild_id: int, text: str, limit: int = 50) -> list[SavedRecipe]:
        query = fts_query(text)
        if not query:
            return []
        cols = ", ".join(f"r.{c.strip()}" for c in RECIPE_COLUMNS.split(","))
        rows = await self._all(
            f"SELECT {cols} FROM recipe_search s JOIN recipes r ON r.id = s.rowid "
            "WHERE recipe_search MATCH ? AND r.guild_id=? ORDER BY s.rank LIMIT ?",
            (query, guild_id, limit))
        return [_saved(r) for r in rows]

    # --- jobs ---------------------------------------------------------------------------

    async def create_job(self, guild_id: int, user_id: int, url: str, backend: str) -> int:
        cur = await self.conn.execute(
            "INSERT INTO jobs (guild_id, user_id, source_url, status, backend, created_at) "
            "VALUES (?, ?, ?, 'queued', ?, ?)", (guild_id, user_id, url, backend, now()))
        await self.conn.commit()
        return cur.lastrowid

    async def job_running(self, job_id: int) -> None:
        await self.conn.execute("UPDATE jobs SET status='running' WHERE id=?", (job_id,))
        await self.conn.commit()

    async def finish_job(
        self, job_id: int, *, error: str | None = None,
        input_tokens: int | None = None, output_tokens: int | None = None,
    ) -> None:
        await self.conn.execute(
            "UPDATE jobs SET status=?, error=?, input_tokens=?, output_tokens=?, finished_at=? WHERE id=?",
            ("failed" if error else "done", error, input_tokens, output_tokens, now(), job_id))
        await self.conn.commit()

    async def jobs_last_24h(self, guild_id: int, user_id: int) -> int:
        since = (datetime.now(UTC) - timedelta(hours=24)).isoformat(timespec="seconds")
        row = await self._one(
            "SELECT count(*) FROM jobs WHERE guild_id=? AND user_id=? AND created_at >= ?",
            (guild_id, user_id, since))
        return row[0]

    async def active_job(self, guild_id: int, url: str) -> bool:
        row = await self._one(
            "SELECT 1 FROM jobs WHERE guild_id=? AND source_url=? AND status IN ('queued', 'running')",
            (guild_id, url))
        return row is not None
