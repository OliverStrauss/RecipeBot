from pathlib import Path

import pytest

from recipe_bot.db import Database, fts_query
from recipe_bot.models import Ingredient, Recipe


def recipe(title: str, items: list[str], tags: list[str]) -> Recipe:
    return Recipe(
        title=title, description="d", servings=None, prep_minutes=None, cook_minutes=None,
        ingredients=[Ingredient(item=i, quantity=None, unit=None, estimated=True, note=None, group=None)
                     for i in items],
        steps=[], equipment=[], tips=[], tags=tags, confidence="high", confidence_note=None, is_recipe=True,
    )


@pytest.fixture
async def db():
    database = Database(Path(":memory:"))
    await database.connect()
    yield database
    await database.close()


async def save(db, guild, user, url, r):
    return await db.save_recipe(guild_id=guild, submitter_id=user, source_url=url,
                                platform="tiktok", creator="chef", recipe=r)


async def test_save_dedupe_and_guild_scoping(db):
    first = await save(db, 1, 10, "u1", recipe("Soup", ["carrots"], ["soup"]))
    again = await save(db, 1, 11, "u1", recipe("Other", ["x"], []))
    assert again.id == first.id and again.recipe.title == "Soup"  # existing one wins
    assert (await db.find_by_url(1, "u1")).submitter_id == 10
    assert await db.find_by_url(2, "u1") is None
    assert await db.get_recipe(2, first.id) is None  # never visible from another server
    other_guild = await save(db, 2, 10, "u1", recipe("Soup 2", ["carrots"], []))
    assert other_guild.id != first.id  # same URL is fine in a different server


async def test_search_by_ingredient_title_and_tag(db):
    soup = await save(db, 1, 10, "u1", recipe("Chicken Noodle Soup", ["chicken thighs", "carrots", "egg noodles"], ["soup"]))
    cake = await save(db, 1, 10, "u2", recipe("Carrot Cake", ["carrots", "eggs", "flour"], ["dessert", "baking"]))
    await save(db, 2, 10, "u3", recipe("Carrot Soup", ["carrots"], []))  # other server

    assert {r.id for r in await db.search(1, "carrot")} == {soup.id, cake.id}
    assert [r.id for r in await db.search(1, "chick")] == [soup.id]  # prefix
    assert [r.id for r in await db.search(1, "dessert")] == [cake.id]  # tag
    assert [r.id for r in await db.search(1, "carrots flour")] == [cake.id]  # all words must match
    assert await db.search(1, '") OR (') == []  # FTS syntax can't break the query
    assert await db.search(1, "   ") == []


async def test_delete_removes_from_search(db):
    r = await save(db, 1, 10, "u1", recipe("Pancakes", ["flour"], []))
    assert await db.delete_recipe(2, r.id) is False  # wrong server
    assert await db.delete_recipe(1, r.id) is True
    assert await db.get_recipe(1, r.id) is None
    assert await db.search(1, "flour") == []


async def test_lists_and_random(db):
    a = await save(db, 1, 10, "u1", recipe("Apple Pie", ["apples"], ["pie", "dessert"]))
    b = await save(db, 1, 11, "u2", recipe("Pierogi", ["potatoes"], ["pierogi"]))
    assert [r.id for r in await db.recent(1)] == [b.id, a.id]
    assert [r.id for r in await db.recipes_by(1, 11)] == [b.id]
    assert (await db.random(1, "pie")).id == a.id  # whole tags only, not "pierogi"
    assert (await db.random(1, "PIEROGI")).id == b.id
    assert await db.random(1, "vegan") is None
    assert await db.random(3) is None


async def test_jobs_and_limits(db):
    assert await db.daily_limit(1, default=15) == 15
    await db.set_daily_limit(1, 3)
    await db.set_recipe_channel(1, 555)
    assert await db.daily_limit(1, default=15) == 3
    assert await db.recipe_channel(1) == 555  # setting one column kept the other

    job = await db.create_job(1, 10, "u1", "claude_cli")
    await db.create_job(1, 10, "u2", "claude_cli")
    await db.create_job(2, 10, "u3", "claude_cli")
    assert await db.jobs_last_24h(1, 10) == 2
    assert await db.active_job(1, "u1")
    await db.finish_job(job, input_tokens=100, output_tokens=20)
    assert not await db.active_job(1, "u1")
    assert await db.jobs_last_24h(1, 10) == 2  # finished jobs still count toward the limit


async def test_restart_fails_stale_jobs(tmp_path):
    path = tmp_path / "r.db"
    first = Database(path)
    await first.connect()
    await first.create_job(1, 10, "u1", "api")
    await first.close()

    second = Database(path)
    await second.connect()
    assert not await second.active_job(1, "u1")
    await second.close()


def test_fts_query_quotes_words():
    assert fts_query("Chicken, thighs!") == '"chicken"* "thighs"*'
    assert fts_query("***") is None
