# TinySLM C2 — candidates v02 (English only)

This version addresses regressions observed in the stratified 180-question
inspection of v01. It is still an **automatic weak-label candidate dataset**,
not a verified fine-tuning dataset.

## Differences vs v01

- A bare `what else` no longer means `ingredients/missing`.
- `substitute` requires an explicit replacement request, not merely the word.
- Dietary requirements have precedence over ingredient-list membership.
- Procedural rewrites use `steps/rewrite`, not ingredient/constraint labels.
- Multi-part questions and uncertain operations are sent to `review`.
- Candidate samples are capped per operation so common templates cannot dominate.
- Includes tests against 26 manually judged cases from the previous 180-row sample.

## Rebuild

```bash
python tools/recipe_intents/build_intents_dataset_v02.py \
  --source /path/to/questions_unique.jsonl \
  --output /path/to/intent_dataset_v02 \
  --max-candidates 30000
```

Unmatched requests are **not** assigned `unknown`. Missing-ingredient lists,
quantities already available, conditional substitutions and mixed intents
need a separate verified slot-annotation stage. Keep C2's old conversational
training set for rehearsal when fine-tuning.

## Quality gate

The file names `train.jsonl`, `validation.jsonl` and `test.jsonl` reflect
recipe-disjoint candidate partitions only. Do **not** treat them as clean
supervision or measure final accuracy against them. An independent human-labeled
test set is essential; recipe-disjointness does not remove repeated phrasing.

Recommended next step: review a stratified sample of v02, report accepted
precision by operation with uncertainty, add true `unknown` and structured
argument examples, then release an explicitly `verified` training version.
