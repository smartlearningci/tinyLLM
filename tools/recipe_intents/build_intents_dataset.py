"""Build a conservative EN-only intent fine-tuning pilot from audited questions.

No external model is used as a labeling oracle. Ambiguous or unmatched questions
go to review, not silently to `unknown`. Splits are recipe-group disjoint.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import random
import re
from pathlib import Path

LABELS = {"ingredients", "quantity", "steps", "constraints", "unknown"}
RULES = [
    # Anchored, explicitly interpretable patterns. Group 1, if present, is an ingredient.
    ("ingredients", "list", r"(?:what|which|list|tell me|give me|could you list|can you list).{0,28}(?:ingredients|spices|herbs)\b"),
    ("ingredients", "check", r"(?:does|do|is|are).{0,35}(?:contain|include|listed|ingredient)\b"),
    ("ingredients", "missing", r"(?:what (?:else|am i missing)|what do i still need|what ingredients am i missing)\b"),
    ("quantity", "get", r"(?:how much|how many (?!minutes|seconds|hours|days)|what (?:amount|quantity|weight|volume|measurement))\b"),
    ("steps", "next", r"(?:what (?:comes|should i do|do i do) (?:immediately )?(?:next|after)|what (?:is|comes) the next step|what comes after)\b"),
    ("steps", "explain", r"(?:how (?:do|should|can) i (?:prepare|cook|make|chop|cut|mix|bake)|which (?:pan|utensil|equipment)|when (?:should|do) i|what (?:heat|texture|cue|oven temperature)|how (?:many|long).{0,25}(?:minutes|seconds|hours))\b"),
    ("constraints", "exclude", r"(?:without (?:the |any )?(?:butter|eggs?|milk|cheese|nuts?|garlic|onions?|flour|dairy|gluten|sugar|salt|oil|meat|fish|cream|cumin|turmeric|walnuts?|peanuts?)|leave out (?:the )?(?:butter|eggs?|milk|cheese|nuts?|garlic|onions?|flour|dairy|gluten|sugar|salt|oil|meat|fish|cream|walnuts?)|omit (?:the )?(?:butter|eggs?|milk|cheese|nuts?|garlic|onions?|flour|dairy|gluten|sugar|salt|oil|meat|fish|cream)|(?:i |we |i'm |we're |need to |must )avoid(?:ing)? (?:butter|eggs?|milk|cheese|nuts?|garlic|onions?|flour|dairy|gluten|sugar|salt|oil|meat|fish|cream|spicy food)|cannot eat|can't eat|allergic to|no (?:butter|eggs|milk|cheese|nuts|dairy|gluten))\b"),
    ("constraints", "check", r"(?:dairy.free|gluten.free|nut.free|egg.free|vegan|vegetarian|as written|unchanged|meet (?:my|the|a) requirement)\b"),
    ("constraints", "substitute", r"(?:what (?:can|could|should) i use instead|substitut(?:e|ion)|replace (?:the|this))\b"),
]
COMPILED = [(a, b, re.compile(c, re.I)) for a, b, c in RULES]


def normalize(question: str) -> str:
    return re.sub(r"\s+", " ", question.strip()).lower()


def classify(question: str) -> tuple[dict | None, str]:
    q = normalize(question)
    if len(q) < 12 or len(q) > 400:
        return None, "length"
    hits = {(intent, op) for intent, op, rx in COMPILED if rx.search(q)}
    intents = {x[0] for x in hits}
    if not hits:
        return None, "unmatched_not_unknown"
    # Weak lexical rules must abstain from multi-task or mixed dietary questions.
    if re.search(r"\b(?:ingredients and steps|steps and ingredients|ingredients and method|method and ingredients)\b", q):
        return None, "explicit_multi_task"
    if re.search(r"\b(?:dairy.free|gluten.free|nut.free|egg.free|alcohol.free|vegan|vegetarian|allergic to|as written|unchanged|meet (?:my|the|a) requirement)\b", q):
        # A dietary requirement takes precedence over mentions of 'ingredient list'.
        if ("constraints", "check") in hits:
            hits = {(x, y) for x, y in hits if x == "constraints"}
    # Preserve multi-intent examples for human review, never fabricate one label.
    if len(intents) > 1:
        return None, "multiple_intents"
    intent = next(iter(intents))
    operations = {x[1] for x in hits}
    # Explicit exclusion takes priority over a generic 'as written' check.
    if intent == "constraints" and "exclude" in operations:
        op = "exclude"
    elif len(operations) == 1:
        op = next(iter(operations))
    else:
        return None, "multiple_operations"
    # Cases requiring slot extraction or context aren't automatically accepted.
    if intent == "ingredients" and op == "missing" and re.search(r"\bi (?:have|got|only have)\b", q):
        return None, "requires_available_ingredients_slots"
    if intent == "constraints" and op == "exclude" and re.search(r"\b(?:instead|substitut|replace)\b", q):
        return None, "exclude_plus_substitution"
    return {"intent": intent, "operation": op}, "rule_candidate"


def split_bucket(recipe_ids: list[str], question: str) -> str:
    # Ambiguous multi-recipe questions are excluded from supervised splits.
    if len(recipe_ids) != 1:
        return "review"
    digest = hashlib.sha256(recipe_ids[0].encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:8], "big") % 100
    return "train" if bucket < 80 else "validation" if bucket < 90 else "test"


def write_row(handle, row):
    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def build(source: Path, output: Path, max_accepted: int, seed: int):
    output.mkdir(parents=True, exist_ok=True)
    paths = {k: output / (k + ".jsonl") for k in ("train", "validation", "test", "review")}
    report = collections.Counter()
    by_label = collections.Counter()
    # Deterministic, limited-size reservoir per split to avoid source-order bias.
    quota = {"train": int(max_accepted * .8), "validation": int(max_accepted * .1)}
    quota["test"] = max_accepted - sum(quota.values())
    buckets = {k: [] for k in quota}
    seen = collections.Counter()
    rng = random.Random(seed)
    with source.open(encoding="utf-8") as stream, paths["review"].open("w", encoding="utf-8") as review:
        for line in stream:
            src = json.loads(line)
            question = src.get("question", "")
            recipe_ids = list(dict.fromkeys(src.get("recipe_ids") or []))
            target, reason = classify(question)
            bucket = split_bucket(recipe_ids, question)
            if target is None or bucket == "review":
                # Review includes provenance but not huge source arrays.
                write_row(review, {"question": question, "reason": reason if target is None else "multiple_recipe_ids",
                                   "recipe_count": len(recipe_ids), "candidate": target,
                                   "capabilities": src.get("capabilities", [])})
                report["review"] += 1
                continue
            # Intent + operation are only weak heuristic labels until reviewed.
            row = {"question": question, "target": target, "recipe_id": recipe_ids[0],
                   "capabilities": src.get("capabilities", []), "label_status": "weak_rule_candidate",
                   "source": "audited_existing_questions"}
            report["eligible"] += 1
            seen[bucket] += 1
            data = buckets[bucket]
            if len(data) < quota[bucket]:
                data.append(row)
            else:
                i = rng.randrange(seen[bucket])
                if i < quota[bucket]:
                    data[i] = row
    # Safety: never call automatically labeled data 'verified'.
    for bucket, rows in buckets.items():
        rng.shuffle(rows)
        with paths[bucket].open("w", encoding="utf-8") as f:
            for row in rows:
                by_label[(bucket, row["target"]["intent"], row["target"]["operation"])] += 1
                write_row(f, row)
        report[bucket] = len(rows)
    summary = {"status": "WEAK_LABELS_REQUIRE_REVIEW_BEFORE_TRAINING",
               "source": str(source), "requested_total": max_accepted,
               "counts": dict(report), "by_label_operation": [{"split": s, "intent": i, "operation": op, "count": n}
                                      for (s, i, op), n in sorted(by_label.items())],
               "warnings": ["Labels are conservative rules, NOT human gold labels.",
                            "Missing or ambiguous classes are review, not unknown.",
                            "No out-of-domain unknown examples exist in this culinary-only source.",
                            "Splits hash one unique recipe ID; broad generic repeated questions may still leak semantically.",
                            "Do not train or report accuracy on these files without quality validation and independent test data."]}
    (output / "build_report.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, required=True, help="questions_unique.jsonl from full audit")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--max-candidates", type=int, default=30000)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    print(json.dumps(build(args.source, args.output, args.max_candidates, args.seed), indent=2))
