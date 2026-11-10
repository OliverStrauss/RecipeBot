"""Recipe web pages: GET /<guild_id>/<recipe_id>. The bot serves these when WEB_URL is set."""

from __future__ import annotations

from aiohttp import web

from .db import Database
from .render import recipe_html

# Pages are escaped text plus inline CSS; the browser may load nothing else.
CSP = "default-src 'none'; style-src 'unsafe-inline'"


def make_app(db: Database) -> web.Application:
    async def page(request: web.Request) -> web.Response:
        # ponytail: anyone with the link can read the page, and ids are guessable within a server.
        # Add a random per-recipe key to the URL if recipes ever need to stay private.
        saved = await db.get_recipe(int(request.match_info["guild"]), int(request.match_info["id"]))
        if saved is None:
            raise web.HTTPNotFound(text="No such recipe.")
        return web.Response(text=recipe_html(saved), content_type="text/html",
                            headers={"Content-Security-Policy": CSP})

    app = web.Application()
    app.router.add_get(r"/{guild:\d{1,19}}/{id:\d{1,18}}", page)
    return app
