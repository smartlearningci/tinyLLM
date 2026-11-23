# TinySLM — Revisão qualitativa de 100 casos C2 (etapa 5)

**Data:** 23/11/2026  \
**Origem:** `manual_review_100.jsonl` do pacote V2; confrontado com `recipes_normalized.sqlite` da etapa 1.  \
**Revisor:** assistente de IA; **não equivale a uma validação humana independente.**

## Metodologia e limites

A amostra foi selecionada deliberadamente com 20 casos por grupo: melhorias lexicais, sem candidatos, gerais, regressões e truncados. **Não usar 12/100 como estimativa de desempenho global** do motor de recuperação. Para cada caso, foi consultada a receita original da SQLite (incluindo `description`, `ingredients_raw` e `method_raw`), os segmentos devolvidos pela V2 e a citação histórica como referência fraca.

- **Relevante**: existe pelo menos um excerto diretamente relacionado com o pedido; pode ser insuficiente.
- **Completo**: os excertos contêm todos os factos/ações essenciais à resposta pedida; mesmo com distratores.
- **Violação**: a evidência contém informação contrária a uma restrição explícita da pergunta (por exemplo, «sem a etapa de servir»).
- **Pedido satisfeito**: relevante + completo + sem violação. Nenhum `INSUFFICIENT_EVIDENCE` desta amostra foi justificado face à receita completa.
- Os campos `human_*` permaneceram **nulos**; a revisão foi gravada sob `assistant_*`.

## Resultados

| Métrica | Casos |
|---|---:|
| Revistos | 100 |
| Com pelo menos um excerto relevante | 60 |
| Com evidência completa (independentemente de distratores) | 16 |
| Com alguma violação de restrição | 26 |
| Pedido estritamente satisfeito | **12** |
| Sem candidatos apesar de existir informação na receita | **20 / 20** |
| Casos com excertos cujas referências existem na SQLite | 80 / 80 |

| Grupo da amostra | Casos | Pedidos satisfeitos |
|---|---:|---:|
| Melhorias lexicais | 20 | 6 |
| Sem candidatos | 20 | 0 |
| Casos gerais | 20 | 5 |
| Regressões lexicais | 20 | 0 |
| Truncados | 20 | 1 |

## Problemas observados e exemplos concretos

### 1. Pesquisa sem candidatos quando existe evidência
Em 18 dos 20 casos a informação aparece em ingredientes e/ou preparação; em **dois casos adicionais** a passagem existe apenas em `description` da receita original (exemplos 21: acompanhamento de iogurte no borrego; 25: referência a legumes grelhados). A V2 indexa exclusivamente `ingredients` e `preparation_segments`, ignorando `description`. Portanto, **nenhum dos 20 `INSUFFICIENT_EVIDENCE` foi justificável à luz da receita completa**.

### 2. Recuperação parcial e etapas omitidas
Exemplo 81 (porco assado com maçã e batata-doce): são recuperados cortar, saco e colocar no tabuleiro, mas faltam explicitamente azeite, xarope e temperos. Exemplo 49 (ovos de brunch): surgem pré-aquecimento e forno; desaparece toda a montagem noturna. Isto inviabiliza ensinar respostas C2 corretas.

### 3. Exclusões e sequências ignoradas
Exemplo 1 (costeletas BBQ): é devolvida a preparação do molho apesar de o utilizador pedir para a excluir. Exemplo 96 (cheesecake delicado): os passos para servir na própria forma estão presentes, mas a resposta de ferramenta também contém a instrução contraditória de levantar o bolo. **26 casos** evidenciam violações explícitas de restrições.

### 4. A métrica lexical é insuficiente
20 casos foram selecionados como melhorias lexicais, mas apenas 6 satisfazem o pedido no critério estrito. O motor devolve mais excertos, incluindo distratores: aumentar overlap com o teacher não mede nem completude semântica nem fidelidade às restrições.

## Prioridades de correção antes de retomar a etapa 5

1. **P0 — Corrigir origem dos excertos:** indexar também `DESCRIPTION` com proveniência, mantendo separação entre conteúdo descritivo, ingredientes estruturados e preparação; rever descrições que contêm texto metodológico fora do parser.
2. **P0 — Evitar falso INSUFFICIENT_EVIDENCE:** antes de declarar ausência, verificar a secção completa para lista de ingredientes/pedidos de todos os passos, incluindo ausência de palavras iguais na pergunta.
3. **P0 — Recuperar sequências completas:** pedido de preparação exige segmentos contíguos necessários, em ordem original, e não 8 passagens isoladas por BM25. Se o contexto exceder o limite de 512 tokens, aplicar seleção/paginação de ferramenta sem afirmar resposta completa.
4. **P0 — Respeitar exclusões:** filtrar passos de servir, acompanhar, finalizar, receitas alternativas e precedência temporal de modo verificável; sinalizar ambiguidades.
5. **P1 — Avaliação de verdade:** construir gabarito independente por receita/pergunta para medir *evidence recall*, completude, violações e abstenções falsas. Métricas por split, idiomas, avisos de parsing e extensão.
6. **P1 — Treino apenas após correção:** não promover os atuais `TOOL RESULT: EVIDENCE_CANDIDATES` a `FOUND` nem usar automaticamente respostas do teacher como verdade.

## Revisão integral caso a caso

| Índice | Receita (título abreviado) | Relevante | Completo | Restrição violada | Satisfeito | Problema |
|---:|---|:---:|:---:|:---:|:---:|---|
| 0 | challah french toast | Sim | Não | Sim | Não | exclusion_and_omission |
| 1 | korean bbq pork chop | Sim | Não | Sim | Não | exclusion_and_omission |
| 2 | leftover turkey and sweet potato | Sim | Não | Não | Não | omitted_steps |
| 3 | crispy asian pizza | Sim | Não | Não | Não | missing_relation |
| 4 | strawberry halloumi cheese salad | Sim | Não | Sim | Não | exclusion_and_omission |
| 5 | steak and baby portobellos | Sim | Sim | Não | Sim | noise_only |
| 6 | peanut butter pie for mikey | Sim | Sim | Não | Sim | noise_only |
| 7 | christmas tree pull apart pizza  | Sim | Não | Não | Não | omitted_steps |
| 8 | cheesy parmesan roasted asparagu | Sim | Não | Não | Não | omitted_steps |
| 9 | jam crumb bars | Sim | Sim | Não | Sim | noise_only |
| 10 | asparagus 'n parmesan omelet | Sim | Sim | Sim | Não | exclusion_noise |
| 11 | gyro salad | Sim | Sim | Não | Sim | noise_only |
| 12 | gluten free soft ginger cookies | Sim | Não | Sim | Não | omitted_steps |
| 13 | ricotta filled squash scones | Sim | Não | Sim | Não | omitted_steps |
| 14 | italian sausage rigatoni | Sim | Não | Não | Não | omitted_steps |
| 15 | orange chicken makeover | Sim | Não | Não | Não | omitted_ingredients |
| 16 | leg of pork with guava and haban | Sim | Não | Não | Não | omitted_steps |
| 17 | smokehouse rub | Sim | Sim | Não | Sim | correct |
| 18 | hanoi tumeric fish with dill cha | Sim | Sim | Não | Sim | noise_only |
| 19 | guajillo pork chops | Sim | Não | Sim | Não | omitted_steps |
| 20 | garlic and ginger bok choy | Não | Não | Não | Não | false_abstention |
| 21 | sam and sam clark's roast should | Não | Não | Não | Não | description_not_indexed |
| 22 | a trout by any other name... | Não | Não | Não | Não | false_abstention |
| 23 | groundhog's day cupcakes | Não | Não | Não | Não | false_abstention |
| 24 | cranberry pomegranate smoothies | Não | Não | Não | Não | false_abstention |
| 25 | eye opening spicy bloody mary ha | Não | Não | Não | Não | description_not_indexed |
| 26 | homemade nut free trail mix | Não | Não | Não | Não | false_abstention |
| 27 | best spicy sweet potato fries | Não | Não | Não | Não | false_abstention |
| 28 | lentil salad | Não | Não | Não | Não | false_abstention |
| 29 | hot 'n spicy chocolate tea | Não | Não | Não | Não | false_abstention |
| 30 | imitation spider crab pate | Não | Não | Não | Não | false_abstention |
| 31 | watermelon on a stick | Não | Não | Não | Não | false_abstention |
| 32 | smashed potatoes w/ gruyere chee | Não | Não | Não | Não | false_abstention |
| 33 | cheeseburger dinner | Não | Não | Não | Não | false_abstention |
| 34 | a trout by any other name... | Não | Não | Não | Não | false_abstention |
| 35 | pbandj fruit kabobs | Não | Não | Não | Não | false_abstention |
| 36 | fiesta ham rollup | Não | Não | Não | Não | false_abstention |
| 37 | bacon wrapped green bean bundles | Não | Não | Não | Não | false_abstention |
| 38 | bang bang chicken salad | Não | Não | Não | Não | false_abstention |
| 39 | knorr pesto roasted vegetables | Não | Não | Não | Não | false_abstention |
| 40 | steak fajitas | Não | Não | Não | Não | wrong_entity |
| 41 | cod with fruit salsa | Sim | Não | Sim | Não | omitted_steps |
| 42 | asparagus and shrimp coconut cur | Sim | Não | Não | Não | omitted_steps |
| 43 | rotisserie chicken and veggies o | Sim | Sim | Não | Sim | correct |
| 44 | pumpkin cupcakes with pumpkin sp | Não | Não | Sim | Não | wrong_section |
| 45 | roasted red pepper hummus | Sim | Sim | Não | Sim | correct |
| 46 | slow cooker southwestern pork ro | Sim | Não | Não | Não | omitted_ingredients |
| 47 | thai chicken fried rice | Sim | Sim | Não | Sim | noise_only |
| 48 | not yo' mama's banana pudding | Sim | Sim | Sim | Não | exclusion_noise |
| 49 | mom's brunch eggs | Não | Não | Não | Não | wrong_stage |
| 50 | knock your stilettos off shooter | Sim | Não | Sim | Não | exclusion_and_omission |
| 51 | strawberry coconut bar | Sim | Sim | Não | Sim | correct |
| 52 | cat fish fillets and rice with c | Sim | Não | Não | Não | omitted_steps |
| 53 | berry quinoa breakfast bowls | Não | Não | Sim | Não | wrong_stage |
| 54 | crustless mini quiches with butt | Sim | Não | Não | Não | omitted_steps |
| 55 | potato bhajee | Sim | Não | Sim | Não | conditional_branch |
| 56 | pear cranberry upside down cake | Sim | Sim | Não | Sim | noise_only |
| 57 | breakfast pizza recipe | Não | Não | Não | Não | omitted_steps |
| 58 | kasha varnishkes kasha and bows | Sim | Não | Não | Não | omitted_steps |
| 59 | roasted turkey tostadas with avo | Sim | Não | Não | Não | omitted_steps |
| 60 | grilled leg of pork | Não | Não | Não | Não | wrong_section |
| 61 | grilled artichokes with parsley  | Não | Não | Sim | Não | wrong_entity |
| 62 | easy creme brulee | Não | Não | Não | Não | missing_instruction |
| 63 | roasted pork chops with autumn m | Sim | Não | Não | Não | omitted_ingredients |
| 64 | quick butterflied roast turkey | Sim | Não | Não | Não | omitted_steps |
| 65 | crispy garlic parmesan potatoes | Não | Não | Não | Não | wrong_section |
| 66 | grilled peach and watermelon bur | Não | Não | Sim | Não | wrong_entity |
| 67 | farm fresh smoked turkey | Não | Não | Não | Não | wrong_section |
| 68 | 82 queens she crab soup | Sim | Não | Não | Não | omitted_ingredients |
| 69 | roasted chicken with lemon and h | Sim | Não | Não | Não | missing_relation |
| 70 | land and sea zitoni | Não | Não | Não | Não | wrong_stage |
| 71 | hash house a go go biscuits | Não | Não | Não | Não | wrong_entity |
| 72 | wilted baby spinach with garlic  | Sim | Não | Não | Não | wrong_section |
| 73 | kelly's barbecue potato chip sea | Não | Não | Não | Não | wrong_stage |
| 74 | mini gluten free polenta pizza | Sim | Não | Não | Não | omitted_ingredients |
| 75 | crispy mustardy chicken thighs w | Não | Não | Não | Não | wrong_section |
| 76 | parmesan mushroom cornish hen | Sim | Não | Não | Não | wrong_entity |
| 77 | easy rosemary garlic parmesan bi | Sim | Não | Não | Não | wrong_section |
| 78 | asian salmon salad | Não | Não | Sim | Não | wrong_entity |
| 79 | lemon pepper chicken and tri col | Sim | Não | Não | Não | omitted_steps |
| 80 | better for you triple chocolate  | Sim | Sim | Sim | Não | exclusion_noise |
| 81 | sheet pan pork chops with sweet  | Sim | Não | Não | Não | omitted_steps |
| 82 | easy cheesy garlic bread | Sim | Não | Não | Não | omitted_steps |
| 83 | saffron rice | Sim | Não | Não | Não | omitted_steps |
| 84 | easy cajun baked salmon | Sim | Não | Sim | Não | exclusion_and_omission |
| 85 | healthy garlicy sweet potato fri | Sim | Não | Não | Não | omitted_steps |
| 86 | mixed berry tartlet with dark ch | Sim | Não | Não | Não | omitted_steps |
| 87 | italian turkey cutlets | Não | Não | Sim | Não | wrong_stage |
| 88 | turkey shepherd's pie | Sim | Sim | Não | Sim | noise_only |
| 89 | italian stuffed peppers | Não | Não | Sim | Não | wrong_stage |
| 90 | the golden girls cheesecake | Não | Não | Não | Não | missing_instruction |
| 91 | arroz con pollo, lightened up | Sim | Não | Não | Não | omitted_steps |
| 92 | rice with shrimp and pineapple | Não | Não | Não | Não | wrong_stage |
| 93 | peanut butter pie for mikey | Sim | Não | Sim | Não | exclusion_and_omission |
| 94 | super cheesy cauliflower "mac" a | Sim | Não | Sim | Não | exclusion_and_omission |
| 95 | dark chocolate mint leaves | Sim | Não | Sim | Não | exclusion_and_omission |
| 96 | the golden girls cheesecake | Sim | Sim | Sim | Não | exclusion_noise |
| 97 | marshmallow sweet potato cassero | Sim | Não | Não | Não | omitted_steps |
| 98 | veal french onion burger | Sim | Não | Sim | Não | exclusion_and_omission |
| 99 | red velvet cupcakes | Sim | Não | Sim | Não | exclusion_and_omission |

Notas explicativas específicas de cada caso estão em `review_100_assistant.csv` e `manual_review_100_assistant_annotated.jsonl` no pacote privado. O GitHub público guarda apenas o sumário e esta matriz resumida, sem receitas completas nem perguntas históricas.

## Estado

**Etapa 5 NÃO aprovada para treino.** A V2 permanece baseline experimental; os dados C2 estão separados como candidatos. Próximo trabalho: implementar as correções P0, repetir esta amostra e realizar avaliação independente representativa.