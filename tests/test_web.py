from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from recipe_bot.db import Database
from recipe_bot.render import recipe_embed
from recipe_bot.web import make_app
from tests.test_render import make_recipe, saved


async def test_recipe_page_served_per_guild():
    db = Database(Path(":memory:"))
    await db.connect()
    r = await db.save_recipe(guild_id=1, submitter_id=2, source_url="u", platform="tiktok",
                             creator="chef", recipe=make_recipe())
    async with TestClient(TestServer(make_app(db))) as client:
        page = await client.get(f"/1/{r.id}")
        assert page.status == 200 and "<h1>Garlic Butter Noodles</h1>" in await page.text()
        assert "default-src 'none'" in page.headers["Content-Security-Policy"]
        assert (await client.get(f"/2/{r.id}")).status == 404  # other server's recipe stays hidden
        assert (await client.get("/1/abc")).status == 404
    await db.close()


def test_embed_title_links_to_page():
    assert recipe_embed(saved(make_recipe()), "https://pi.example")[0].url == "https://pi.example/1/42"
    assert recipe_embed(saved(make_recipe()))[0].url == "https://www.tiktok.com/@chef/video/1"
