from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from recipe_bot.cogs.library import Library, Paginator
from recipe_bot.db import Database
from tests.test_db import recipe


@pytest.fixture
async def library():
    db = Database(Path(":memory:"))
    await db.connect()
    for n in range(12):
        await db.save_recipe(guild_id=1, submitter_id=10, source_url=f"u{n}", platform="tiktok", creator=None,
                             recipe=recipe(f"Garlic Dish {n}", ["garlic"], []))
    await db.save_recipe(guild_id=1, submitter_id=10, source_url="cake", platform="tiktok", creator=None,
                         recipe=recipe("Cake", ["flour"], ["dessert"]))
    yield Library(SimpleNamespace(db=db))
    await db.close()


def interaction():
    i = MagicMock(guild_id=1)
    i.response.send_message = AsyncMock()
    i.response.edit_message = AsyncMock()
    i.original_response = AsyncMock()
    return i


async def test_search_paginates(library):
    i = interaction()
    await library.search.callback(library, i, query="garlic")
    kwargs = i.response.send_message.await_args.kwargs
    assert kwargs["embed"].footer.text.startswith("Page 1/2")
    view: Paginator = kwargs["view"]
    assert view.prev.disabled and not view.next.disabled

    click = interaction()
    await view.next.callback(click)
    assert click.response.edit_message.await_args.kwargs["embed"].footer.text.startswith("Page 2/2")
    assert view.next.disabled and not view.prev.disabled


async def test_search_single_page_and_no_results(library):
    i = interaction()
    await library.search.callback(library, i, query="flour")
    assert "view" not in i.response.send_message.await_args.kwargs
    assert "Cake" in i.response.send_message.await_args.kwargs["embed"].description

    none = interaction()
    await library.search.callback(library, none, query="tofu")
    assert none.response.send_message.await_args.kwargs["ephemeral"] is True


async def test_random_by_tag(library):
    i = interaction()
    await library.random.callback(library, i, tag="dessert")
    assert i.response.send_message.await_args.kwargs["embed"].title == "Cake"
