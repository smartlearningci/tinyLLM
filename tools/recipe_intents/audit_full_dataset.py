"""Read-only audit of every user question in TinySLM train.jsonl.

Produces an index of unique questions, conservative intent *candidates*,
validation diagnostics and an audit sample. No labels are certified and no
training/validation/test sets are reassigned automatically.
"""

import argparse
import collections
import hashlib
import json
import random
import re
from pathlib import Path


PATTERNS = {
    "ingredients": [r"\bingredients?\b", r"\bspices?\b", r"\bseasonings?\b",
                    r"\bherbs?\b", r"\bshopping list\b"],
    "quantity": [r"\bhow much\b", r"\bhow many\b", r"\bquantit(?:y|ies)\b",
                 r"\b(?:amount|measurements?|grams?|cups?|teaspoons?|tablespoons?)\b"],
    "steps": [r"\b(?:next|first|last) step\b", r"\bwhat (?:comes|happens) (?:next|after)\b",
              r"\bafter (?:boiling|cooking|adding|draining|mixing)\b",
              r"\bwhen (?:do|should|can) i\b", r"\b(?:steps?|instructions?|method)\b"],
    "constraints": [r"\bwithout\b", r"\bfree[- ]of\b", r"\bavoid\b",
                    r"\b(?:allerg(?:y|ic|en)|exclude|restriction)\b",
                    r"\b(?:contain|contains|include|includes)\b"],
}


def normalize(value):
    return re.sub(r"\s+", " ", value.casefold()).strip()


def candidate_intents(question):
    """Deliberately broad markers; overlaps are informative, not errors."""
    s = normalize(question)
    return [intent for intent, patterns in PATTERNS.items()
            if any(re.search(pattern, s) for pattern in patterns)]


def audit(source, output, sample_per_group=30):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    records = {}
    stats = collections.Counter()
    caps = collections.Counter()
    original_splits = collections.Counter()
    original_statuses = collections.Counter()
    languages = collections.Counter()
    recipes_by_split = collections.defaultdict(set)
    splits_by_question = collections.defaultdict(set)
    splits_by_recipe = collections.defaultdict(set)
    malformed = 0

    with Path(source).open(encoding="utf-8") as source_file:
        for line in source_file:
            if not line.strip():
                continue
            stats["source_rows"] += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            capability = row.get("capability") or "missing"
            split = row.get("split") or "missing"
            recipe_id = str(row.get("recipe_id") or "missing")
            caps[capability] += 1
            original_splits[split] += 1
            original_statuses[str(row.get("validation_status") or "missing")] += 1
            recipes_by_split[split].add(recipe_id)
            splits_by_recipe[recipe_id].add(split)
            for turn in row.get("conversation", []):
                if turn.get("role") != "user" or not isinstance(turn.get("content"), str):
                    continue
                question = turn["content"].strip()
                if not question:
                    continue
                stats["question_occurrences"] += 1
                key = normalize(question)
                splits_by_question[key].add(split)
                record = records.get(key)
                if record is None:
                    record = {"question": question, "count": 0,
                              "capabilities": set(), "splits": set(), "recipe_ids": set(),
                              "validation_statuses": set(),
                              "candidate_intents": candidate_intents(question),
                              "label_status": "heuristic_candidates_unverified"}
                    records[key] = record
                record["count"] += 1
                record["capabilities"].add(capability)
                record["splits"].add(split)
                record["recipe_ids"].add(recipe_id)
                record["validation_statuses"].add(str(row.get("validation_status") or "missing"))

    candidate_totals = collections.Counter()
    overlaps = collections.Counter()
    cap_intent = collections.defaultdict(collections.Counter)
    for record in records.values():
        candidates = record["candidate_intents"]
        group = "no_marker" if not candidates else "multiple_markers" if len(candidates) > 1 else candidates[0]
        overlaps[group] += 1
        for candidate in candidates:
            candidate_totals[candidate] += 1
            for cap in record["capabilities"]:
                cap_intent[cap][candidate] += 1

    index = output / "questions_unique.jsonl"
    with index.open("w", encoding="utf-8") as handle:
        for record in sorted(records.values(), key=lambda item: (-item["count"], item["question"])):
            item = dict(record)
            for field in ("capabilities", "splits", "recipe_ids", "validation_statuses"):
                item[field] = sorted(item[field])
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    rng = random.Random(20261119)
    sample = []
    for group in ("ingredients", "quantity", "steps", "constraints", "multiple_markers", "no_marker"):
        candidates = [record for record in records.values()
                      if ("no_marker" if not record["candidate_intents"] else
                          "multiple_markers" if len(record["candidate_intents"]) > 1 else
                          record["candidate_intents"][0]) == group]
        for item in rng.sample(candidates, min(sample_per_group, len(candidates))):
            sample.append({"question": item["question"], "group": group,
                           "candidate_intents": item["candidate_intents"],
                           "capabilities": sorted(item["capabilities"]),
                           "human_intent": None, "review_notes": ""})
    rng.shuffle(sample)
    with (output / "review_sample.jsonl").open("w", encoding="utf-8") as handle:
        for item in sample:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    repeated = [record for record in records.values() if record["count"] > 1]
    report = {
        "source_rows": stats["source_rows"], "malformed_rows": malformed,
        "question_occurrences": stats["question_occurrences"],
        "unique_questions_normalized": len(records),
        "duplicate_question_occurrences": stats["question_occurrences"] - len(records),
        "questions_repeated": len(repeated),
        "recipes_unique": len(splits_by_recipe),
        "source_capabilities": dict(sorted(caps.items())),
        "source_splits": dict(sorted(original_splits.items())),
        "source_validation_status": dict(sorted(original_statuses.items())),
        "unique_recipes_per_split": {k: len(v) for k, v in sorted(recipes_by_split.items())},
        "recipes_in_multiple_splits": sum(len(v) > 1 for v in splits_by_recipe.values()),
        "questions_in_multiple_splits": sum(len(v) > 1 for v in splits_by_question.values()),
        "unique_questions_by_marker_group": dict(sorted(overlaps.items())),
        "candidate_markers_by_intent_nonexclusive": dict(sorted(candidate_totals.items())),
        "capability_by_intent_candidate_nonexclusive": {k: dict(v) for k, v in sorted(cap_intent.items())},
        "top_repeated_questions": [
            {"question": item["question"], "occurrences": item["count"],
             "recipes": len(item["recipe_ids"])}
            for item in sorted(repeated, key=lambda x: -x["count"])[:20]],
        "review_sample_size": len(sample),
        "warnings": [
            "Markers are NOT class labels. No model was trained or evaluated by this audit.",
            "No-marker questions are NOT automatically out of domain.",
            "A question can match several markers and require manual review.",
            "Exact normalized duplicates do not detect paraphrases or near-duplicates.",
            "Original dataset splits are reported, not trusted as contamination-free.",
        ],
    }
    (output / "audit_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--sample-per-group", type=int, default=30)
    args = parser.parse_args()
    print(json.dumps(audit(args.source, args.out, args.sample_per_group), indent=2, ensure_ascii=False))
