"""Write saved recipes as HTML pages: ``python -m recipe_bot.export [id ...]`` (no ids = all)."""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv

from .db import RECIPE_COLUMNS, _saved
from .render import recipe_html


def main(ids: list[int]) -> int:
    load_dotenv()
    db = Path(os.environ.get("DB_PATH") or "./data/recipes.db").expanduser()
    if not db.exists():
        print(f"No database at {db}", file=sys.stderr)
        return 1
    sql = f"SELECT {RECIPE_COLUMNS} FROM recipes"
    if ids:
        sql += f" WHERE id IN ({','.join('?' * len(ids))})"
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)  # read-only: safe while the bot runs
    rows = conn.execute(sql, ids).fetchall()
    conn.close()

    out = db.parent / "html"
    out.mkdir(exist_ok=True)
    for row in rows:
        saved = _saved(row)
        path = out / f"recipe-{saved.id}.html"
        path.write_text(recipe_html(saved), encoding="utf-8")
        print(path)
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(main([int(x) for x in sys.argv[1:]]))
