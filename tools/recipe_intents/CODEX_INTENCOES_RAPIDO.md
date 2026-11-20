# Geração rápida de intenções — Codex CLI no PC

Usa só a **pergunta**, sem receita nem `recipe_id` no prompt. A saída do
professor é apenas `id`, `intent`, `operation`, sem justificações nem confiança
inventada. Por omissão: modelo `gpt-6-luna`, raciocínio `low`, 8 perguntas por
lote e 8 trabalhadores. Aceita até 12 trabalhadores.

## Testar a versão otimizada (sem interferir com a ronda anterior)

Na raiz do projeto, depois de `git pull origin main`:

```bash
python tools/recipe_intents/codex_generate_intents.py \
  --input dados/intents_teacher/pilot_200_questions.jsonl \
  --out dados/intents_teacher/pilot_200_rapido \
  --limit 200 --batch-size 8 --workers 8 --dry-run
```

Executar as chamadas reais, removendo `--dry-run`:

```bash
python tools/recipe_intents/codex_generate_intents.py \
  --input dados/intents_teacher/pilot_200_questions.jsonl \
  --out dados/intents_teacher/pilot_200_rapido \
  --limit 200 --batch-size 8 --workers 8
```

Isto cria **25 lotes**. O ensaio anterior de 3 perguntas por lote continua
intacto noutra pasta. Comparar a concordância e o número de lotes válidos,
assim como o tempo e os tokens por classificação, antes de lançar produção.

## Retoma e limites

Lotes completos são preservados. As combinações novas de intenção/operação
ficam com `taxonomy_warning=true`; não desaparecem por divergirem da taxonomia.
Se uma chamada falhar, não a reenvia automaticamente numa nova execução.
Recuperar primeiro as respostas dos eventos com `--recover-events` e só depois
repetir falhas identificadas explicitamente com `--retry-errors`.

Um erro explícito de quota sinaliza os outros trabalhadores para **não iniciar**
novos lotes; chamadas já em curso podem terminar. Isto evita continuar a
lançar chamadas indiscriminadamente, mas não assegura que a quota dure mais.

Para produzir mais exemplos, usa um ficheiro de perguntas fixo e uma nova
pasta `--out` por experiência; nunca mudes a ordem nem o `--batch-size` de
uma execução parcialmente concluída. A saída permanece `teacher_unverified`.
