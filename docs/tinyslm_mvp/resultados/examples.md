# Exemplos reais e curtos da normalização

São excertos para conferir o formato. O conteúdo integral e os originais
encontram-se no dataset separado (não publicado diretamente no Git).

## Receitas sem avisos automáticos

### mexican wedding cookies

`recipe_id`: `recipe_nlg_lite:00187d20-040d-45a3-984b-7de4a58f5b22`

```text
RECIPE
TITLE: mexican wedding cookies
INGREDIENTS (excerto):
- 0.8 cup pecans
- 1.0 cup unsalted butter
PREPARATION (excerto):
1. finely chop pecans
```

### sun dried tomato fettuccine

`recipe_id`: `recipe_nlg_lite:00397d00-e2ab-4570-8b56-12ad1548d045`

```text
RECIPE
TITLE: sun dried tomato fettuccine
INGREDIENTS (excerto):
- 1.0 pound basic egg pasta dough
- 2.0 tablespoon olive oil
PREPARATION (excerto):
1. attach pasta sheet roller to kitchenaid stand mixer
```

### chipotle's cilantro lime rice

`recipe_id`: `recipe_nlg_lite:004720d5934e904ec8d3c4d61bc98c63e5be1b00`

```text
RECIPE
TITLE: chipotle's cilantro lime rice
INGREDIENTS (excerto):
- 1 cup extra long grain rice or basmati rice
- 1/2 lime
PREPARATION (excerto):
1. in a small heavy pot, add rice, water, 1 tsp oil and salt
```

## Receitas com avisos de parsing

### beef lasagna from donna hay long cooking

`recipe_id`: `recipe_nlg_lite:00073cf5-3952-4764-ab04-63c0286dc2cd`

Aviso: `uncertain_ingredient_comma` (noutra entrada da receita).

```text
RECIPE
TITLE: beef lasagna from donna hay long cooking
INGREDIENTS (excerto):
- 2.0 kilogram beef shoulder
- 2.0 tablespoon olive oil
```

### greek salad the best feta vinaigrette

`recipe_id`: `recipe_nlg_lite:000d93ea-b2f9-45e9-979d-af9bb02c6599`

Aviso: `uncertain_ingredient_comma` (noutro ingrediente).

```text
RECIPE
TITLE: greek salad the best feta vinaigrette
INGREDIENTS (excerto):
- 1.0 lemon
- 2.0 tablespoon red wine vinegar
```

### grilled pizza

`recipe_id`: `recipe_nlg_lite:001f39722f97db2755e26358f905b50d86029eaf`

Aviso: `uncertain_ingredient_comma` (noutro ingrediente).

```text
RECIPE
TITLE: grilled pizza
INGREDIENTS (excerto):
- 1 cup all purpose or white whole wheat flour
- 1 1/2 teaspoons baking powder
```

Os avisos não provam que a receita esteja errada. A segregação de ingredientes
e a divisão dos segmentos de preparação são heurísticas e continuam sujeitas
a revisão; o original é sempre preservado.
