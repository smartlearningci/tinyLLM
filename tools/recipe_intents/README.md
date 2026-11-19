# TinySLM — Recipe tools, MVP ingredients + quantities + steps (English)

This directory contains three external tools: retrieve ingredients, look up
quantities and consult the preparation steps of the recipe currently open.
The application supplies `recipe_id`;
there is no attempt to guess a recipe title from the user's question.

## Local files

Put the following previously generated files in this directory:

- `recipes.sqlite` — local source recipe database (not committed to GitHub).
- `local_model/intent_model.joblib` — classifier **retrained locally** with the
  installed scikit-learn version (not committed to GitHub).
- `intents_2000.jsonl` — only needed if retraining; not needed to run this tool.

The database and trained model are local generated artifacts. Keep them out of
Git commits. The GitHub repository contains the code and these instructions.

## 1. Find a real recipe ID

In DBeaver run:

```sql
SELECT recipe_id, title FROM recipes LIMIT 5;
```

Copy a recipe ID exactly. For the original sample database, the first recipe is:

`recipe_nlg_lite:8a4002df3b72ad39013b9146ff023f10`

## 2. Test the data tool without the classifier

From `tools/recipe_intents`:

```bash
python recipe_tools.py --database recipes.sqlite --recipe-id "recipe_nlg_lite:8a4002df3b72ad39013b9146ff023f10"
```

It returns JSON with `ingredients_raw` (original evidence) and `ingredients`
(best-effort structured parsing). `parse_status: unverified` applies to every
entry: **do not present parsed quantities as independently verified facts**.

## 3. Test intent classification + ingredient retrieval

```bash
python recipe_tools.py --database recipes.sqlite --model local_model/intent_model.joblib --recipe-id "recipe_nlg_lite:8a4002df3b72ad39013b9146ff023f10" --question "What ingredients do I need?"
```

`ingredients`, `quantity` and `steps` are routed. Other intents return
`not_implemented`; uncertain classifications return `clarify`. Unknown recipe
IDs return `recipe_not_found`. The system does **not** call TinySLM yet.

## 4. Query one explicit ingredient

```bash
python recipe_tools.py --database recipes.sqlite --recipe-id "recipe_nlg_lite:8a4002df3b72ad39013b9146ff023f10" --ingredient "paprika"
```

Or ask in natural English with the locally trained classifier:

```bash
python recipe_tools.py --database recipes.sqlite --model local_model/intent_model.joblib --recipe-id "recipe_nlg_lite:8a4002df3b72ad39013b9146ff023f10" --question "How much paprika should I use?"
```

The tool returns the quantity and source fragment (for this sample,
`2.0 teaspoon paprika`). If several items match, it returns
`ambiguous_ingredient` or `clarify_ingredient`. If no ingredient matches, it
returns `ingredient_not_found`; if no amount exists, `quantity_not_specified`.
It does not infer missing numbers or choose between ambiguous ingredients.

## 5. Query steps of the preparation

Read the full original method and heuristic step breakdown:

```bash
python recipe_tools.py --database recipes.sqlite --recipe-id "recipe_nlg_lite:8a4002df3b72ad39013b9146ff023f10" --step-number 1
```

For the natural-language question "What should I do next?", the **interface
must supply the current 1-based step**. Example: the user is on step 2.

```bash
python recipe_tools.py --database recipes.sqlite --model local_model/intent_model.joblib --recipe-id "recipe_nlg_lite:8a4002df3b72ad39013b9146ff023f10" --current-step 2 --question "What should I do next?"
```

The example returns position 3, "add onions to same skillet...". Without a
current step, the natural-language next-step request returns
`current_step_required`. At the end of the preparation it returns
`no_next_step`.

An exact source phrase can be searched without a classifier:

```bash
python recipe_tools.py --database recipes.sqlite --recipe-id "recipe_nlg_lite:8a4002df3b72ad39013b9146ff023f10" --after-text "remove lamb from skillet"
```

The method is split by the corpus's ` . ` separators, so a resulting position
is **not guaranteed to be a single culinary action**. A phrase occurring in
multiple steps returns `ambiguous_step`. The `method_raw` field is retained
as the authoritative source. Complex questions such as "When should I add
garlic?" receive the full method for subsequent reasoning, not an invented
single-step answer. The TinySLM response integration is still pending.

## 6. Run automated tests

From the repository root:

```bash
python -m unittest discover -s tools/recipe_intents -v
```

## Next implementation steps

1. Review segmentation edge cases and maintain the original source for audit.
2. Add the deterministic constraint tool and improve step segmentation after audit.
3. Integrate with the app's active `recipe_id` and then with TinySLM.
4. Evaluate complete answers against real recipes and unseen English questions.
