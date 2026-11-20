# TinySLM C2 — candidate dataset for structured intents (English only)

This is **dataset preparation**, not a fine-tuning job. Do **not** mistake weak
automatic candidate labels for independently validated supervision.

## Source

Use `questions_unique.jsonl` produced by `tools/recipe_intents/audit_full_dataset.py`
from the existing C1–C7 training conversations. The audit preserves questions,
recipe IDs and capabilities. The source is not downloaded from the internet.

## Build

From the repository root:

```bash
python tools/recipe_intents/build_intents_dataset.py \
  --source path/to/questions_unique.jsonl \
  --output data/intents_candidates_v01 \
  --max-candidates 30000
```

Output: `train.jsonl`, `validation.jsonl`, `test.jsonl`, `review.jsonl`,
`build_report.json`.

**Important:** Files named `train`/`validation`/`test` contain **weak rule candidates**
marked `label_status: weak_rule_candidate`. These files are **not ready for
fine-tuning**. A label-review stage must certify accepted examples and set
an explicit approval status before a training notebook may consume them.

The builder abstains on ambiguous, mixed-intent, insufficiently specified and
unmatched questions. It does **not** automatically label unmatched culinary
questions as `unknown`. An independent dataset of clearly nonculinary questions
is needed for that category. Complex `missing`, `compare` and `substitute`
examples need separately verified argument/slot extraction.

Current targets are `intent` and `operation`; no recipe contents are sent to
the intent model. Slot extraction comes after reliable labeling and validation.

## Evaluation safeguards

1. Assign each singly-linked recipe to a train/validation/test partition by
   deterministic SHA-256, avoiding recipe overlap for accepted candidates.
2. Review the rareness of each operation (`missing` and `substitute` are scarce).
3. Manually check a stratified sample with exact question and reference label.
4. Reserve **independent** human-written questions for final evaluation.
5. Deduplicate/cluster paraphrases across splits; recipe-disjointness alone
   does not prevent near-duplicate wording leakage.
6. Mix certified intent examples with former culinary response examples during
   fine-tuning, and measure both tasks after fine-tuning.

The pilot count of 30,000 is a **capacity target**, not a measured number of
human-verified examples. Never claim classification quality from weak labels.
