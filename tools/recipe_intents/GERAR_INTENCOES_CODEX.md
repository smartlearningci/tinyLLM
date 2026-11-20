# Dataset de intenções — Codex CLI no PC

Segue a estratégia já utilizada em `economico.py`: sessão ChatGPT autenticada com
`codex login`, `codex exec` sem aprovações, schema JSON obrigatório, lotes,
processamento paralelo e resultados guardados antes da exportação.

## Primeiro ensaio (12 perguntas)

Na raiz do repositório `tinyLLM`:

```bash
git pull origin main
unzip -o data/intent_candidates/TinySLM_C2_intents_candidates_v02.zip
codex login status
python tools/recipe_intents/codex_generate_intents.py \
  --input intent_dataset_v02/train.jsonl --limit 12 --batch-size 3 \
  --workers 2 --dry-run
python tools/recipe_intents/codex_generate_intents.py \
  --input intent_dataset_v02/train.jsonl --limit 12 --batch-size 3 --workers 2
```

O modelo por omissão é `gpt-6-luna`, raciocínio `low`, tal como em `economico.py`.
Pode ajustar `--model`, `--reasoning`, `--workers` e `--batch-size`.
Não definir `OPENAI_API_KEY` nem `CODEX_API_KEY`: usa a sessão ChatGPT do Codex.
Este processamento está sujeito aos limites de utilização da tua conta.

Resultados em `dados/intents_teacher/batches/` e agregado em
`dados/intents_teacher/teacher_intents_unverified.jsonl`.
O script não volta a processar lotes concluídos e válidos, mas permite
reexecutar lotes falhados. Não altera o checkpoint, o dataset original ou a BD.
Combinações novas propostas pelo professor (por exemplo `steps/get`) ficam
preservadas com `teacher.taxonomy_warning=true` para revisão da taxonomia;
não são tratadas como rótulos automaticamente aprovados.

Se uma versão anterior rejeitou um lote completo por incompatibilidade
`intent/operation`, recuperar diretamente as respostas registadas em
`batches/batch_*.events.jsonl` **sem gastar novas chamadas**:

```bash
python tools/recipe_intents/codex_generate_intents.py \
  --input intent_dataset_v02/train.jsonl --limit 12 --batch-size 3 \
  --workers 2 --recover-events
```

**Segurança operacional:** usar inicialmente 12 perguntas e 2 trabalhadores.
Antes de aumentar o volume, rever qualidade, contagens de erros e consumo.
Para retoma consistente, manter o mesmo ficheiro de entrada, a mesma ordem e
`--batch-size`; criar nova pasta de `--out` para outra experiência.
O conjunto completo deve ser revisto e dividido sem fuga de treino para teste.

**Qualidade:** `teacher_unverified` significa rótulo produzido por IA, não
validação humana. A saída é uma proposta de supervisão; não lançar treino nem
publicar precisão como métrica independente sem controlo de qualidade.
