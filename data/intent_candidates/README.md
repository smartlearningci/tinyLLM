# TinySLM C2 — English intent candidates v01

Dataset archive: `TinySLM_C2_intents_candidates_v01.zip` (SHA-256:
`82ad978151539f37e356a5591c97bb51058bbbbf63ae7d2b012b989e347aa6dd`).

Generated deterministically from 156,872 distinct audited questions with:

```bash
python tools/recipe_intents/build_intents_dataset.py \
  --source path/to/questions_unique.jsonl \
  --output intent_dataset_v01 \
  --max-candidates 30000
```

Archive contents:

| File | Records | Purpose |
| --- | ---: | --- |
| `train.jsonl` | 24,000 | **Unverified** train candidates |
| `validation.jsonl` | 3,000 | **Unverified** validation candidates |
| `test.jsonl` | 3,000 | **Unverified** test candidates |
| `review.jsonl` | 113,640 | Ambiguous/unmatched cases needing labeling |
| `build_report.json` | 1 | Summary, cautions, label distribution |

**Not ready for model fine-tuning.** Candidate labels originate from conservative
text rules. They are not human-validated ground truth. `unknown` and structured
ingredient-availability slots still need separately curated supervision.

To inspect locally:

```bash
unzip -l data/intent_candidates/TinySLM_C2_intents_candidates_v01.zip
unzip -p data/intent_candidates/TinySLM_C2_intents_candidates_v01.zip intent_dataset_v01/build_report.json
```

Keep the ZIP versioned with the generator and commit, so the preliminary data
can be recovered in the same repository. Do not include the full 457 MB source
conversation dataset in Git without a separate storage decision.
