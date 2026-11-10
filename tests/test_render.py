import pytest
from pydantic import ValidationError

from recipe_bot.models import Ingredient, Recipe, SavedRecipe, Step
from recipe_bot.pipeline.extract.base import parse_recipe
from recipe_bot.render import (
    DESCRIPTION_LIMIT, EMBED_LIMIT, format_ingredient, list_pages, recipe_embed, recipe_html, recipe_markdown,
)


def make_recipe(steps: int = 3, **overrides) -> Recipe:
    data = dict(
        title="Garlic Butter Noodles", description="Quick weeknight noodles.", servings="2",
        prep_minutes=5, cook_minutes=10,
        ingredients=[
            Ingredient(item="noodles", quantity="200", unit="g", estimated=False, note=None, group=None),
            Ingredient(item="soy sauce", quantity="2", unit="tbsp", estimated=False, note="low sodium", group="Sauce"),
            Ingredient(item="chili flakes", quantity="1/2", unit="tsp", estimated=True, note=None, group="Sauce"),
        ],
        steps=[Step(number=n, text=f"Do step {n}. " * 5, duration_minutes=n) for n in range(1, steps + 1)],
        equipment=["wok"], tips=["Save some pasta water."], tags=["noodles", "quick"],
        confidence="high", confidence_note=None, is_recipe=True,
    )
    return Recipe(**{**data, **overrides})


def saved(recipe: Recipe) -> SavedRecipe:
    return SavedRecipe(42, 1, 777, "https://www.tiktok.com/@chef/video/1", "tiktok", "chef", recipe, "2026-11-09")


def test_format_ingredient():
    assert format_ingredient(Ingredient(item="soy sauce", quantity="2", unit="tbsp", estimated=False,
                                        note="low sodium", group=None)) == "2 tbsp soy sauce, low sodium"
    assert format_ingredient(Ingredient(item="salt", quantity="1/2", unit="tsp", estimated=True,
                                        note=None, group=None)) == "~1/2 tsp salt (est.)"
    assert format_ingredient(Ingredient(item="salt", quantity=None, unit=None, estimated=False,
                                        note="to taste", group=None)) == "salt, to taste"


def test_small_recipe_fits_one_embed():
    embed, file = recipe_embed(saved(make_recipe()))
    assert file is None
    d = embed.description
    assert "Serves 2 · Prep 5 min · Cook 10 min" in d
    assert "*Sauce*\n- 2 tbsp soy sauce, low sodium\n- ~1/2 tsp chili flakes (est.)" in d
    assert "3. Do step 3." in d and "(~3 min)" in d
    assert "From [@chef](https://www.tiktok.com/@chef/video/1) on TikTok · saved by <@777> · Recipe #42" in d
    assert "⚠" not in d
    assert embed.footer.text == "Tags: noodles, quick"


def test_low_confidence_warning():
    embed, _ = recipe_embed(saved(make_recipe(confidence="low", confidence_note="recipe was gated behind a DM")))
    assert "⚠ Confidence: low. recipe was gated behind a DM" in embed.description


def test_long_recipe_falls_back_to_markdown_file():
    recipe = make_recipe(steps=60)
    embed, file = recipe_embed(saved(recipe))
    assert file is not None and file.filename == "recipe-42.md"
    assert len(embed.description) <= DESCRIPTION_LIMIT and len(embed) <= EMBED_LIMIT
    assert "attached as a file" in embed.description and "Recipe #42" in embed.description
    md = file.fp.read().decode()
    assert md.startswith("# Garlic Butter Noodles")
    assert "60. Do step 60." in md and "## Equipment\n- wok" in md and "### Sauce" in md


def test_markdown_has_everything():
    md = recipe_markdown(saved(make_recipe()))
    for part in ("## Ingredients", "## Steps", "## Tips", "Tags: noodles, quick", "@chef on TikTok", "Recipe #42"):
        assert part in md


def test_html_page():
    page = recipe_html(saved(make_recipe(title="Mac & <Cheese>", confidence="low", confidence_note="guessed")))
    assert "<title>Mac &amp; &lt;Cheese&gt;</title>" in page  # escaped
    assert "<h3>Sauce</h3>" in page and "~1/2 tsp chili flakes (est.)" in page
    assert page.count('<input type=checkbox>') == 3 and "~3 min" in page
    assert "⚠ Confidence: low. guessed" in page and 'href="https://www.tiktok.com/@chef/video/1"' in page


def test_list_pages():
    items = [saved(make_recipe(title=f"Recipe {n}")) for n in range(23)]
    pages = list_pages(items, "Recent")
    assert len(pages) == 3
    assert pages[0].footer.text.startswith("Page 1/3")
    assert pages[2].description.count("\n") == 2  # 3 entries on the last page
    assert list_pages([], "Mine")[0].description == "Nothing here yet."


def test_parse_recipe_accepts_fences_and_numbers():
    data = make_recipe().model_dump()
    data["servings"] = 4  # Claude sometimes sends numbers for string fields
    import json
    recipe = parse_recipe(f"Here you go:\n```json\n{json.dumps(data)}\n```")
    assert recipe.servings == "4"


def test_parse_recipe_rejects_bad_confidence():
    data = make_recipe().model_dump() | {"confidence": "very"}
    with pytest.raises(ValidationError):
        parse_recipe(data)
