# Ensaio estratificado C2 — 200 perguntas no PC

Na raiz do repositório, depois de `git pull origin main`:

```bash
unzip -o data/intent_candidates/TinySLM_C2_intents_candidates_v02.zip
python tools/recipe_intents/make_stratified_pilot.py
python tools/recipe_intents/codex_generate_intents.py \
  --input dados/intents_teacher/pilot_200_questions.jsonl \
  --out dados/intents_teacher/pilot_200 \
  --limit 200 --batch-size 3 --workers 2 --dry-run
```

Depois de confirmar a amostra, tirar `--dry-run`:

```bash
python tools/recipe_intents/codex_generate_intents.py \
  --input dados/intents_teacher/pilot_200_questions.jsonl \
  --out dados/intents_teacher/pilot_200 \
  --limit 200 --batch-size 3 --workers 2
```

O piloto inclui 20 exemplos de cada uma das 8 operações candidatas, 20
perguntas explicitamente fora do domínio culinário e 20 perguntas compostas
potencialmente ambíguas. **Estas últimas não são exemplos `unknown`
verificados**: são candidatos para o professor e para revisão.

O processamento prevê 67 lotes, no máximo dois simultâneos. Pode ser retomado
com o mesmo comando; lotes concluídos são ignorados. Não misturar os resultados
com os 12 exemplos do ensaio anterior. A saída agregada ficará em
`dados/intents_teacher/pilot_200/teacher_intents_unverified.jsonl`.

Em caso de erros, inspecionar `batches/batch_*.error.txt`; se os eventos tiverem
respostas completas, usar `--recover-events` com os mesmos argumentos.
Interromper se ocorrer limite de utilização Codex; evitar aumentar trabalhadores
antes de medir a taxa de falhas. Comparar classificações do professor com os
rótulos fracos não equivale a medir exatidão face a rótulos humanos.
