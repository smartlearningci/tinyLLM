# TinySLM — Recipe tools, MVP 1 + quantity lookup (English)

This directory contains two external tools: retrieve ingredient data and
look up an ingredient's quantity for the recipe currently open in the app.
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

`ingredients` and `quantity` are routed. Other intents return
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

## 5. Run automated tests

From the repository root:

```bash
python -m unittest discover -s tools/recipe_intents -v
```

## Next implementation steps

1. Review segmentation edge cases and maintain the original source for audit.
2. Add deterministic step and constraint tools.
3. Integrate with the app's active `recipe_id` and then with TinySLM.
4. Evaluate complete answers against real recipes and unseen English questions.
