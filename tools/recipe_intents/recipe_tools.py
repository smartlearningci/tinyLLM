"""First TinySLM tool: source-grounded ingredient lookup for the active recipe.

No network access, no TinySLM call, and no changes to the SQLite database.
Every ingredient keeps its original source fragment for auditability.
"""

import argparse
import json
import re
import sqlite3
from pathlib import Path


QUANTITY = re.compile(r"^\s*(\d+(?:\.\d+)?|\d+/\d+)\s+(.+?)\s*$")
UNITS = frozenset({
    "teaspoon", "teaspoons", "tablespoon", "tablespoons", "tsp", "tbsp",
    "cup", "cups", "ounce", "ounces", "oz", "pound", "pounds", "lb", "lbs",
    "gram", "grams", "g", "kilogram", "kilograms", "kg", "ml", "milliliter",
    "milliliters", "liter", "liters", "l", "clove", "cloves", "jar", "jars",
    "can", "cans", "pinch", "pinches", "slice", "slices", "bunch", "bunches",
})


def parse_ingredient(fragment):
    """Separate explicit numbers/units; never infer missing culinary detail."""
    raw = fragment.strip()
    match = QUANTITY.match(raw)
    if not match:
        return {"raw": raw, "quantity": None, "unit": None,
                "name": raw, "parse_status": "unverified"}

    amount, remainder = match.groups()
    if "/" in amount:
        numerator, denominator = map(int, amount.split("/"))
        quantity = numerator / denominator if denominator else None
    else:
        quantity = float(amount)
    if quantity is not None and quantity.is_integer():
        quantity = int(quantity)

    words = remainder.split(maxsplit=1)
    unit = words[0] if len(words) > 1 and words[0].casefold() in UNITS else None
    name = words[1] if unit else remainder
    return {"raw": raw, "quantity": quantity, "unit": unit,
            "name": name, "parse_status": "unverified"}


def get_recipe_ingredients(database, recipe_id):
    """Return original ingredient text for an exact, app-supplied recipe ID."""
    db = Path(database).resolve()
    if not db.is_file():
        return {"status": "database_not_found", "recipe_id": recipe_id,
                "message": "The recipe database is unavailable."}

    # mode=ro ensures this tool cannot accidentally modify the user's database.
    with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True) as connection:
        row = connection.execute(
            "SELECT recipe_id, title, ingredients_raw FROM recipes WHERE recipe_id = ?",
            (recipe_id,),
        ).fetchone()

    if row is None:
        return {"status": "recipe_not_found", "recipe_id": recipe_id,
                "message": "The active recipe was not found in the database."}

    rid, title, original = row
    if not original.strip():
        return {"status": "ingredients_unavailable", "recipe_id": rid,
                "title": title, "message": "The source does not list ingredients."}

    # This source uses comma-delimited entries; internal commas may be ambiguous.
    fragments = [part.strip() for part in original.split(",") if part.strip()]
    return {
        "status": "ok", "recipe_id": rid, "title": title,
        "ingredients_raw": original,
        "ingredients": [parse_ingredient(part) for part in fragments],
        "source_status": "original_source_preserved",
        "parse_warning": "Ingredient segmentation is heuristic and not verified; use ingredients_raw as the authoritative text.",
    }


def handle_question(database, recipe_id, question, model_path):
    """Classify natural-language intent; only ingredients are supported in MVP 1."""
    try:
        import joblib
    except ImportError as exc:
        raise RuntimeError("Install scikit-learn and joblib first.") from exc

    model = joblib.load(model_path)  # Trusted local model only.
    scores = model.predict_proba([question])[0]
    intent, confidence = max(zip(model.classes_, scores), key=lambda item: item[1])
    confidence = float(confidence)
    if confidence < 0.65:
        return {"status": "clarify", "intent": str(intent),
                "confidence": round(confidence, 3),
                "message": "Please clarify what you would like to know about this recipe."}
    if intent != "ingredients":
        return {"status": "not_implemented", "intent": str(intent),
                "confidence": round(confidence, 3),
                "message": "This request type is not implemented in MVP 1."}
    result = get_recipe_ingredients(database, recipe_id)
    result.update({"intent": "ingredients", "confidence": round(confidence, 3)})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="recipes.sqlite")
    parser.add_argument("--recipe-id", required=True)
    parser.add_argument("--question", help="Natural language question; requires --model")
    parser.add_argument("--model", help="Locally retrained intent_model.joblib")
    args = parser.parse_args()
    if bool(args.question) != bool(args.model):
        parser.error("Use --question and --model together, or neither.")
    if args.question:
        result = handle_question(args.database, args.recipe_id, args.question, args.model)
    else:
        result = get_recipe_ingredients(args.database, args.recipe_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
