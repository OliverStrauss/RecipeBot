"""The Recipe schema both Claude backends must return (PLAN.md section 6)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict


class _Model(BaseModel):
    # Claude sometimes writes 4 instead of "4" for servings/quantity; accept it.
    model_config = ConfigDict(coerce_numbers_to_str=True)


class Ingredient(_Model):
    item: str  # "soy sauce"
    quantity: str | None  # "2", "1/2", "a pinch"
    unit: str | None  # "tbsp", "g", None
    estimated: bool  # True if the video didn't state the amount
    note: str | None  # "low sodium", "divided"
    group: str | None  # "Sauce", "Marinade" (recipes with components)


class Step(_Model):
    number: int
    text: str
    duration_minutes: int | None  # if a time is given or clearly implied


class Recipe(_Model):
    title: str
    description: str  # 1-2 sentences
    servings: str | None
    prep_minutes: int | None
    cook_minutes: int | None
    ingredients: list[Ingredient]
    steps: list[Step]
    equipment: list[str]
    tips: list[str]  # creator tips worth keeping
    tags: list[str]  # "chicken", "air fryer", "vegetarian", "dessert"...
    confidence: Literal["high", "medium", "low"]
    confidence_note: str | None  # why it's not high
    is_recipe: bool  # False if the video isn't actually a recipe


@dataclass(frozen=True)
class SavedRecipe:
    """A row from the recipes table."""

    id: int
    guild_id: int
    submitter_id: int
    source_url: str
    platform: str
    creator: str | None
    recipe: Recipe
    created_at: str
