# TinySLM C2 — 20.000 classificações do professor (v01)

O ZIP `TinySLM_C2_teacher_20000_v01.zip` foi produzido pelo Codex CLI no PC
e contém as **20.000 perguntas únicas** e as respetivas classificações. As
etiquetas têm estado `teacher_unverified`: não foram revistas individualmente
por humanos.

**Proveniência:** a resposta do `batch_001278` tinha um carácter incorreto
num ID (`...f68f` em vez de `...f68b`). A correspondência foi confirmada com
os outros sete IDs e com a fila original, e o ID corrigido no ficheiro de
eventos para recuperação. Os oito rótulos foram preservados; a cópia do
evento original permanece no PC onde se executou o Codex.

`TinySLM_C2_intents_sft_v01.zip` é o pacote **experimental** para Kaggle,
gerado por `tools/recipe_intents/build_teacher_sft_dataset.py`. Contém:

| Ficheiro | Exemplos | Observações |
| --- | ---: | --- |
| `train.jsonl` | 17.783 | 17.748 do professor + 35 perguntas fora do domínio curadas pelo assistente |
| `validation.jsonl` | 1.040 | Referências do professor, separadas por `recipe_id` |
| `test.jsonl` | 1.027 | 1.012 do professor + 15 fora do domínio curadas pelo assistente |
| `review_warnings.jsonl` | 200 | Combinações intenção/operação a rever, excluídas do treino |
| `sft_report.json` | — | Totais, proveniência, checksums e limitações |

As 5.136 perguntas válidas sem `recipe_id` foram destinadas **apenas ao treino**.
O teste de intenções não recebe o contexto da receita. A revisão de 200 casos
está em `teacher_review_sample_v01.csv` (150 amostras estratificadas e 50
anomalias). Ainda falta uma avaliação humana independente antes de declarar
precisão ou colocar em produção.

Reconstrução determinística:

```bash
python tools/recipe_intents/build_teacher_sft_dataset.py \
  --input data/intent_teacher/TinySLM_C2_teacher_20000_v01.zip \
  --output data/intent_teacher/TinySLM_C2_intents_sft_v01.zip \
  --review data/intent_teacher/teacher_review_sample_v01.csv
```

Notebook: `notebooks/TinySLM_C2_v09_refinamento_intencoes.ipynb`.
