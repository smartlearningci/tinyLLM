"""R1/R2 predecessor: lossless, audited natural-language recipe normalization.

Run with Python's standard library only:

    python tools/tinyslm_mvp/normalize_audit_recipes.py \
        --source /path/to/recipes.sqlite --output /path/to/output

The source is opened read-only. Outputs are not overwritten, even on reruns.
The intermediate structured records are for the application; only the
``canonical_text`` field is intended as input to the 51M TinySLM.
"""

from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import re
import sqlite3
from pathlib import Path

SCHEMA = "tinyslm-natural-recipe-v13.0"
QUANTITY = r"(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:[.,]\d+)?)"
# The recipe_nlg_lite source concatenates entries with comma + new quantity.
ENTRY_START = re.compile(rf",\s*(?={QUANTITY}\s+)")
ENTRY_QUANTITY = re.compile(rf"^(?P<qty>{QUANTITY})\s+(?P<rest>.+)$")
SEGMENT_SPLIT = re.compile(r"\s+\.\s+")
SPACES = re.compile(r"\s+")
UNITS = frozenset("""
    tablespoon tablespoons teaspoon teaspoons tbsp tsp gram grams g kilogram
    kilograms kg ounce ounces oz pound pounds lb lbs cup cups ml milliliter
    milliliters liter liters l clove cloves jar jars can cans pinch pinches
    slice slices bunch bunches head heads pint pints dash dashes piece pieces
    stick sticks packet packets package packages bottle bottles sheet sheets
    handful handfuls
""".split())


def compact(value: str) -> str:
    return SPACES.sub(" ", (value or "").strip())


def source_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_ingredients(raw: str) -> tuple[list[dict], set[str]]:
    source = compact(raw)
    if not source:
        return [], {"ingredients_missing"}
    fragments = [x.strip() for x in ENTRY_START.split(source) if x.strip()]
    items: list[dict] = []
    warnings: set[str] = set()
    for position, fragment in enumerate(fragments, 1):
        found = ENTRY_QUANTITY.match(fragment)
        quantity, unit, name = None, None, fragment
        if found:
            quantity = found.group("qty")
            rest = found.group("rest").strip()
            parts = rest.split(maxsplit=1)
            if len(parts) > 1 and parts[0].lower() in UNITS:
                unit, name = parts[0], parts[1]
            else:
                name = rest
            if not name.strip():
                warnings.add("empty_ingredient_name")
        else:
            warnings.add("ingredient_without_leading_quantity")
        if "," in fragment:
            # Could be a valid descriptive comma OR an unsplit source entry.
            warnings.add("uncertain_ingredient_comma")
        if any(char in fragment for char in "[]{}"):
            warnings.add("special_ingredient_characters")
        items.append({
            "position": position, "raw": fragment, "name": name,
            "quantity_text": quantity, "unit": unit,
            "parse_status": "needs_review" if "," in fragment
                            else "heuristic" if quantity else "raw_only",
        })
    if ", ".join(x["raw"] for x in items) != source:
        # Real source contains malformed ", ," delimiters and occasional
        # comma-spacing variants. Preserve the exact raw field and warn.
        # A parsed ingredient list is never authoritative in these cases.
        warnings.add("ingredient_delimiters_not_roundtrippable")
    return items, warnings


def parse_preparation(raw: str) -> tuple[list[dict], set[str]]:
    source = compact(raw)
    if not source:
        return [], {"preparation_missing"}
    segments = []
    for pos, fragment in enumerate(SEGMENT_SPLIT.split(source), 1):
        raw_piece = fragment.strip()
        if not raw_piece:
            continue
        text = re.sub(r"^\d+\.\s*", "", raw_piece) if pos == 1 else raw_piece
        segments.append({"position": pos, "text": text,
                         "raw": raw_piece, "parse_status": "heuristic_segment"})
    if compact(" . ".join(s["raw"] for s in segments)) != source:
        raise ValueError("preparation fragments do not reconstruct source")
    warnings: set[str] = set()
    if len(segments) < 2:
        warnings.add("preparation_fewer_than_two_segments")
    if len(segments) > 30:
        warnings.add("preparation_more_than_thirty_segments")
    return segments, warnings


def extract_description(original: str) -> tuple[str, bool]:
    found = re.search(r"(?:^|\n)Description:\s*(.*?)\n\s*Ingredients:",
                      original, flags=re.IGNORECASE | re.DOTALL)
    return (compact(found.group(1)), True) if found else ("", False)


def canonical_text(title: str, description: str, ingredients: list[dict],
                   segments: list[dict]) -> str:
    # Only natural-language text, with predictable section headings and order.
    # Keep source ingredient phrases intact; do not hallucinate units.
    lines = ["RECIPE", f"TITLE: {title}",
             "DESCRIPTION: " + (description or "Not given in the source."),
             "INGREDIENTS:"]
    lines.extend(f"- {entry['raw']}" for entry in ingredients)
    if not ingredients:
        lines.append("- Not given in the source.")
    lines.append("PREPARATION:")
    lines.extend(f"{part['position']}. {part['text']}" for part in segments)
    if not segments:
        lines.append("- Not given in the source.")
    return "\n".join(lines)


def normalize(row: sqlite3.Row) -> dict:
    ingredients, iw = parse_ingredients(row["ingredients_raw"])
    preparation, pw = parse_preparation(row["method_raw"])
    description, has_description = extract_description(row["original_text"])
    warnings = iw | pw
    if not has_description:
        warnings.add("description_not_extracted")
    if "ingredient_delimiters_not_roundtrippable" in iw:
        # Keep the entire source ingredient string visible to the LLM;
        # no silently dropped malformed delimiter in canonical text.
        ingredient_lines = [{"raw": row["ingredients_raw"]}]
    else:
        ingredient_lines = ingredients
    title = compact(row["title"])
    if not title:
        warnings.add("title_missing")
    return {
        "schema_version": SCHEMA,
        "recipe_id": row["recipe_id"], "source_id": row["source_id"],
        "title": title, "description": description,
        "canonical_text": canonical_text(title, description, ingredient_lines, preparation),
        "ingredients": ingredients, "preparation_segments": preparation,
        "original": {"text": row["original_text"],
                     "ingredients_raw": row["ingredients_raw"],
                     "method_raw": row["method_raw"]},
        "warnings": sorted(warnings),
        "review_status": "needs_review" if warnings else "source_preserved",
        "training_approved": False,
    }


def initialize_db(c: sqlite3.Connection) -> None:
    c.executescript("""
        CREATE TABLE recipes (
            recipe_id TEXT PRIMARY KEY, source_id TEXT NOT NULL,
            title TEXT NOT NULL, description TEXT NOT NULL,
            canonical_text TEXT NOT NULL, original_text TEXT NOT NULL,
            ingredients_raw TEXT NOT NULL, method_raw TEXT NOT NULL,
            warnings_json TEXT NOT NULL, review_status TEXT NOT NULL);
        CREATE TABLE ingredients (
            recipe_id TEXT NOT NULL, position INTEGER NOT NULL,
            raw TEXT NOT NULL, name TEXT NOT NULL, quantity_text TEXT,
            unit TEXT, parse_status TEXT NOT NULL,
            PRIMARY KEY (recipe_id, position));
        CREATE TABLE preparation_segments (
            recipe_id TEXT NOT NULL, position INTEGER NOT NULL,
            text TEXT NOT NULL, raw TEXT NOT NULL, parse_status TEXT NOT NULL,
            PRIMARY KEY (recipe_id, position));
        CREATE INDEX idx_ingredients_recipe_name ON ingredients(recipe_id, name);
    """)


def run(source: Path, output: Path, historical_count: int = 5108) -> dict:
    source = source.resolve()
    output = output.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    source_sha256 = source_hash(source)
    output.mkdir(parents=True, exist_ok=True)
    full = output / "recipes_normalized.jsonl.gz"
    review = output / "review_queue.jsonl.gz"
    normalized_db = output / "recipes_normalized.sqlite"
    report_path = output / "audit_report.json"
    examples_path = output / "examples.md"
    for path in (full, review, normalized_db, report_path, examples_path):
        if path.exists():
            raise FileExistsError(f"output already exists; choose new output directory: {path}")

    counters: collections.Counter = collections.Counter()
    per_warning: collections.Counter = collections.Counter()
    title_count: collections.Counter = collections.Counter()
    examples_clean, examples_review = [], []
    ids: set[str] = set()

    with sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True) as original, \
         sqlite3.connect(normalized_db) as target, \
         gzip.open(full, "wt", encoding="utf-8", compresslevel=6) as stream, \
         gzip.open(review, "wt", encoding="utf-8", compresslevel=6) as review_stream:
        original.row_factory = sqlite3.Row
        initialize_db(target)
        count_source = original.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]
        for row in original.execute("SELECT * FROM recipes ORDER BY recipe_id"):
            record = normalize(row)
            rid = record["recipe_id"]
            if rid in ids:
                raise ValueError(f"repeated recipe_id: {rid}")
            ids.add(rid)
            title_count[record["title"].casefold()] += 1
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            target.execute("INSERT INTO recipes VALUES (?,?,?,?,?,?,?,?,?,?)", (
                rid, record["source_id"], record["title"], record["description"],
                record["canonical_text"], record["original"]["text"],
                record["original"]["ingredients_raw"],
                record["original"]["method_raw"],
                json.dumps(record["warnings"]), record["review_status"]))
            target.executemany("INSERT INTO ingredients VALUES (?,?,?,?,?,?,?)", [
                (rid, i["position"], i["raw"], i["name"], i["quantity_text"],
                 i["unit"], i["parse_status"]) for i in record["ingredients"]])
            target.executemany("INSERT INTO preparation_segments VALUES (?,?,?,?,?)", [
                (rid, s["position"], s["text"], s["raw"], s["parse_status"])
                for s in record["preparation_segments"]])
            counters["recipes"] += 1
            counters["ingredients"] += len(record["ingredients"])
            counters["preparation_segments"] += len(record["preparation_segments"])
            counters["ingredients_raw_only"] += sum(
                i["parse_status"] == "raw_only" for i in record["ingredients"])
            counters["ingredients_ambiguous"] += sum(
                i["parse_status"] == "needs_review" for i in record["ingredients"])
            for warning in record["warnings"]:
                per_warning[warning] += 1
            if record["warnings"]:
                counters["recipes_for_review"] += 1
                review_stream.write(json.dumps({
                    "recipe_id": rid, "title": record["title"],
                    "warnings": record["warnings"],
                    "original_ingredients": record["original"]["ingredients_raw"],
                    "original_method": record["original"]["method_raw"],
                }, ensure_ascii=False) + "\n")
                if len(examples_review) < 3:
                    examples_review.append(record)
            elif len(examples_clean) < 3:
                examples_clean.append(record)
        target.commit()
        # Strict 1:1 checks, including original fields and segment counts.
        count_output = target.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]
        assert count_source == count_output == counters["recipes"] == len(ids)
        assert target.execute("SELECT COUNT(*) FROM ingredients").fetchone()[0] == counters["ingredients"]
        assert target.execute("SELECT COUNT(*) FROM preparation_segments").fetchone()[0] == counters["preparation_segments"]
        original_text_mismatches = 0
        for row in original.execute("SELECT * FROM recipes"):
            out = target.execute(
                "SELECT source_id, original_text, ingredients_raw, method_raw "
                "FROM recipes WHERE recipe_id=?", (row["recipe_id"],)).fetchone()
            if out != (row["source_id"], row["original_text"],
                       row["ingredients_raw"], row["method_raw"]):
                original_text_mismatches += 1
        if original_text_mismatches:
            raise ValueError(f"source fields changed for {original_text_mismatches} records")

    duplicated_titles = sum(n - 1 for n in title_count.values() if n > 1)
    report = {
        "schema": SCHEMA,
        "source_filename": source.name, "source_sha256": source_sha256,
        "historical_catalog_count": historical_count,
        "source_available_count": count_source,
        "difference_vs_historical_count": historical_count - count_source,
        "count_difference_is_missing_recipe_proof": False,
        "source_rows_preserved": count_output,
        "all_original_fields_exact": original_text_mismatches == 0,
        "repeated_recipe_ids": 0,
        "duplicate_titles_extra_rows": duplicated_titles,
        "counts": dict(counters), "warnings_per_type": dict(per_warning),
        "unreviewed_recipe_count": counters["recipes_for_review"],
        "training_approved_count": 0,
        "ready_for_unqualified_training": False,
        "source_language": "English (source unchanged)",
        "limitations": [
            "The catalog of 5108 and the local 5025-recipe export may differ in provenance; IDs cannot be reconciled without the historical source.",
            "Ingredient delimiters and preparation segments are heuristic; all original source fields are preserved byte-for-byte as Python strings.",
            "Warnings require review; absence of warnings does not certify factual correctness.",
            "The original texts are not translated or silently truncated.",
            "No training, model evaluation or C1/C2 acceptance was performed.",
        ],
    }
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = ["# Exemplos REAIS de normalização (auditáveis)",
             "", "A fonte original encontra-se no dataset completo e em SQLite."]
    for heading, entries in (("Sem avisos automáticos", examples_clean),
                             ("Com avisos e revisão pendente", examples_review)):
        lines += ["", f"## {heading}"]
        for record in entries:
            lines += ["", f"### {record['title']}",
                      f"`recipe_id`: `{record['recipe_id']}`", "",
                      "Avisos: " + (", ".join(record["warnings"]) or "nenhum"),
                      "", "```text", "RECIPE",
                      f"TITLE: {record['title']}",
                      "INGREDIENTS (amostra curta):"]
            lines.extend(f"- {entry['raw']}" for entry in record["ingredients"][:2])
            lines.append("PREPARATION (amostra curta):")
            lines.extend(f"{segment['position']}. {segment['text'][:95]}"
                         for segment in record["preparation_segments"][:1])
            lines.append("```")
    examples_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True,
                   help="SQLite with recipes, opened read-only")
    p.add_argument("--output", type=Path, required=True,
                   help="New output directory (never overwrite existing artefacts)")
    p.add_argument("--historical-count", type=int, default=5108)
    args = p.parse_args()
    print(json.dumps(run(args.source, args.output, args.historical_count),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
