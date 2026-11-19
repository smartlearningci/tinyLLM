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


def get_recipe_steps(database, recipe_id, current_step=None, step_number=None,
                     after_text=None, find_text=None):
    """Return source method or conservatively selected steps (1-based indexes).

    Without an explicit step or clear phrase, return the full method. Never
    treat the heuristic split as an audited sequence of cooking actions.
    """
    db = Path(database).resolve()
    if not db.is_file():
        return {"status": "database_not_found", "recipe_id": recipe_id,
                "message": "The recipe database is unavailable."}
    with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True) as connection:
        row = connection.execute(
            "SELECT title, method_raw FROM recipes WHERE recipe_id = ?", (recipe_id,)
        ).fetchone()
    if row is None:
        return {"status": "recipe_not_found", "recipe_id": recipe_id,
                "message": "The active recipe was not found in the database."}
    title, original = row
    if not original.strip():
        return {"status": "steps_unavailable", "recipe_id": recipe_id,
                "title": title, "message": "The recipe has no preparation method."}

    fragments = [re.sub(r"^(?:\d+\.\s*)+", "", part.strip())
                 for part in re.split(r"\s+\.\s+", original) if part.strip()]
    steps = [{"position": i, "raw": part, "parse_status": "unverified"}
             for i, part in enumerate(fragments, 1)]
    base = {"recipe_id": recipe_id, "title": title,
            "method_raw": original, "steps": steps,
            "parse_warning": "Steps are split heuristically on source punctuation; original method_raw is authoritative."}

    selectors = sum(value is not None for value in (current_step, step_number, after_text, find_text))
    if selectors > 1:
        return {"status": "invalid_selection", "message": "Use one step selector at a time."}
    if selectors == 0:
        return dict(base, status="ok")
    if current_step is not None or step_number is not None:
        index = (current_step + 1) if current_step is not None else step_number
        if not isinstance(index, int) or index < 1:
            return {"status": "invalid_step", "recipe_id": recipe_id,
                    "message": "Step numbers must be positive integers (1-based)."}
        if index > len(steps):
            return {"status": "no_next_step" if current_step is not None else "step_not_found",
                    "recipe_id": recipe_id, "title": title, "step_count": len(steps)}
        return dict(base, status="ok", selected_step=steps[index - 1])

    phrase = after_text if after_text is not None else find_text
    matches = [i for i, step in enumerate(steps)
               if _contains_phrase(step["raw"], phrase)]
    if not matches:
        return {"status": "step_not_found", "recipe_id": recipe_id, "title": title,
                "message": "The specified action was not found in the method."}
    if len(matches) > 1:
        return {"status": "ambiguous_step", "recipe_id": recipe_id, "title": title,
                "candidates": [steps[i] for i in matches],
                "message": "The action appears in multiple steps."}
    index = matches[0] + (1 if after_text is not None else 0)
    if index >= len(steps):
        return {"status": "no_next_step", "recipe_id": recipe_id, "title": title}
    return dict(base, status="ok", selected_step=steps[index])


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


def handle_question(database, recipe_id, question, model_path, current_step=None):
    """Classify natural-language intent; route available source-backed tools."""
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
    if intent == "steps":
        lowered = question.casefold()
        if re.search(r"\b(?:first step|how (?:do i|should i) start|where do i start)\b", lowered):
            result = get_recipe_steps(database, recipe_id, step_number=1)
        elif re.search(r"\b(?:next step|what (?:do i|should i) do next|what comes next)\b", lowered):
            if current_step is None:
                return {"status": "current_step_required", "intent": "steps",
                        "confidence": round(confidence, 3),
                        "message": "Please identify your current recipe step."}
            result = get_recipe_steps(database, recipe_id, current_step=current_step)
        else:
            # A method can be returned intact for questions that require
            # reasoning over the sequence; do not hallucinate a specific step.
            result = get_recipe_steps(database, recipe_id)
        result.update({"intent": "steps", "confidence": round(confidence, 3)})
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
    parser.add_argument("--current-step", type=int, help="Current 1-based step; only with --question")
    parser.add_argument("--step-number", type=int, help="Select a source step, without classifier")
    parser.add_argument("--after-text", help="Find the step after an exact action phrase")
    parser.add_argument("--find-text", help="Find a step containing an exact phrase")
    args = parser.parse_args()
    step_selectors = (args.step_number, args.after_text, args.find_text)
    if sum(x is not None for x in step_selectors) > 1:
        parser.error("Use only one step selector.")
    if args.ingredient and (args.question or args.model or any(x is not None for x in step_selectors)):
        parser.error("Use --ingredient alone, without other selectors.")
    if any(x is not None for x in step_selectors) and (args.question or args.model):
        parser.error("Use explicit step selectors without --question and --model.")
    if args.current_step is not None and not args.question:
        parser.error("--current-step requires --question and --model.")
    if bool(args.question) != bool(args.model):
        parser.error("Use --question and --model together, or neither.")
    if args.ingredient:
        result = get_ingredient_quantity(args.database, args.recipe_id, args.ingredient)
    elif args.question:
        result = handle_question(args.database, args.recipe_id, args.question, args.model,
                                 current_step=args.current_step)
    elif any(x is not None for x in step_selectors):
        result = get_recipe_steps(args.database, args.recipe_id,
                                  step_number=args.step_number, after_text=args.after_text,
                                  find_text=args.find_text)
    else:
        result = get_recipe_ingredients(args.database, args.recipe_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
