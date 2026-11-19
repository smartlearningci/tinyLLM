"""TinySLM tools: source-grounded ingredient list and quantity lookup.

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


def _words(text):
    """Tokenize English ingredient names without relying on a language model."""
    return re.findall(r"[a-z0-9]+", text.casefold())


def _contains_phrase(haystack, needle):
    """Match full word sequences, not arbitrary substrings (oil != boil)."""
    words = _words(haystack)
    target = _words(needle)
    return bool(target) and any(words[i:i + len(target)] == target
                                for i in range(len(words) - len(target) + 1))


def get_ingredient_quantity(database, recipe_id, ingredient_name):
    """Read a quantity only when the requested source ingredient is unambiguous."""
    result = get_recipe_ingredients(database, recipe_id)
    if result["status"] != "ok":
        return result
    if not ingredient_name or not _words(ingredient_name):
        return {"status": "ingredient_unspecified", "recipe_id": recipe_id,
                "message": "Which ingredient do you mean?"}

    matches = [entry for entry in result["ingredients"]
               if _contains_phrase(entry["name"], ingredient_name)]
    if not matches:
        return {"status": "ingredient_not_found", "recipe_id": recipe_id,
                "title": result["title"], "ingredient_requested": ingredient_name,
                "message": "The requested ingredient was not found in this recipe."}
    if len(matches) > 1:
        return {"status": "ambiguous_ingredient", "recipe_id": recipe_id,
                "title": result["title"], "ingredient_requested": ingredient_name,
                "candidates": [entry["raw"] for entry in matches],
                "message": "More than one ingredient matches. Please be more specific."}

    entry = matches[0]
    if entry["quantity"] is None:
        return {"status": "quantity_not_specified", "recipe_id": recipe_id,
                "title": result["title"], "ingredient": entry,
                "message": "The recipe does not specify a numeric quantity for this ingredient."}
    return {"status": "ok", "recipe_id": recipe_id, "title": result["title"],
            "ingredient_requested": ingredient_name, "ingredient": entry,
            "source_status": "original_fragment_preserved",
            "parse_warning": "Quantity and unit extraction is heuristic; verify against ingredient.raw."}


def _quantity_ingredient_from_question(question, entries):
    """Choose only an ingredient phrase literally present in the question.

    A generic question like 'How much do I need?' must request clarification.
    Multiple matches are deliberately left ambiguous.
    """
    candidates = []
    for entry in entries:
        tokens = _words(entry["name"])
        # Accept an exact ingredient phrase or one of its substantive words.
        matches = [" ".join(tokens)] + [token for token in tokens if len(token) >= 4]
        if any(_contains_phrase(question, phrase) for phrase in matches):
            candidates.append(entry["name"])
    return candidates


def handle_question(database, recipe_id, question, model_path):
    """Classify natural-language intent; route ingredients and quantities only."""
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
    if intent == "quantity":
        source = get_recipe_ingredients(database, recipe_id)
        if source["status"] != "ok":
            return source
        candidates = _quantity_ingredient_from_question(question, source["ingredients"])
        if len(candidates) != 1:
            return {"status": "clarify_ingredient", "intent": "quantity",
                    "confidence": round(confidence, 3),
                    "candidates": candidates,
                    "message": "Which specific ingredient are you asking about?"}
        result = get_ingredient_quantity(database, recipe_id, candidates[0])
        result.update({"intent": "quantity", "confidence": round(confidence, 3)})
        return result
    if intent != "ingredients":
        return {"status": "not_implemented", "intent": str(intent),
                "confidence": round(confidence, 3),
                "message": "This request type is not implemented yet."}
    result = get_recipe_ingredients(database, recipe_id)
    result.update({"intent": "ingredients", "confidence": round(confidence, 3)})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="recipes.sqlite")
    parser.add_argument("--recipe-id", required=True)
    parser.add_argument("--question", help="Natural language question; requires --model")
    parser.add_argument("--model", help="Locally retrained intent_model.joblib")
    parser.add_argument("--ingredient", help="Look up an explicit ingredient quantity (without classifier)")
    args = parser.parse_args()
    if args.ingredient and (args.question or args.model):
        parser.error("Use --ingredient alone, without --question or --model.")
    if bool(args.question) != bool(args.model):
        parser.error("Use --question and --model together, or neither.")
    if args.ingredient:
        result = get_ingredient_quantity(args.database, args.recipe_id, args.ingredient)
    elif args.question:
        result = handle_question(args.database, args.recipe_id, args.question, args.model)
    else:
        result = get_recipe_ingredients(args.database, args.recipe_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
