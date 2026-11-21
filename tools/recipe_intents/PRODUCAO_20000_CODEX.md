# Produção de 20.000 intenções com Codex no PC

Objetivo: obter **20.000 classificações provisórias** a partir de perguntas
distintas, sem enviar texto da receita ao Codex. Os rótulos gerados são do
professor (`teacher_unverified`), não um conjunto humano de treino validado.

## 1. Preparar a fila

Depois de `git pull origin main`, na raiz do repositório, **utilizar a fila já
preparada** (assim o conjunto de perguntas fica igual ao auditado):

```bash
mkdir -p dados/intents_teacher
unzip -o data/intent_candidates/TinySLM_C2_teacher_queue_20000_v01.zip \
  -d dados/intents_teacher
```

Se for necessário **reconstruir** a fila em vez de usar o ZIP, usar:

```bash
unzip -o data/intent_candidates/TinySLM_C2_intents_candidates_v02.zip
python tools/recipe_intents/make_production_questions.py \
  --exclude dados/intents_teacher/pilot_200_questions.jsonl
```

O ficheiro `dados/intents_teacher/production_20000_questions.jsonl` contém
20.000 perguntas únicas. O relatório correspondente guarda contagens por
origem e SHA-256; manter ambos estáveis até terminar a produção.

As perguntas provêm dos candidatos de treino v02 e de perguntas incertas da
fila de revisão; as perguntas da validação e teste v02 são excluídas por texto
normalizado. Perguntas incertas **não são etiquetadas `unknown` por regra**:
o Codex fará a classificação. Não misturar as etiquetas do professor com
rótulos humanos verificados.

## 2. Primeira ronda (2.000) e continuação para 20.000

Fazer primeiro uma simulação, sem consumir quota:

```bash
python tools/recipe_intents/codex_generate_intents.py \
  --input dados/intents_teacher/production_20000_questions.jsonl \
  --out dados/intents_teacher/production_20000 \
  --limit 2000 --batch-size 8 --workers 8 --dry-run
```

Se estiver tudo certo, executar as 2.000 primeiras perguntas:

```bash
python tools/recipe_intents/codex_generate_intents.py \
  --input dados/intents_teacher/production_20000_questions.jsonl \
  --out dados/intents_teacher/production_20000 \
  --limit 2000 --batch-size 8 --workers 8
```

Depois de confirmar os lotes e a qualidade de uma amostra, continuar na **mesma
pasta** e com o mesmo `--batch-size`:

```bash
python tools/recipe_intents/codex_generate_intents.py \
  --input dados/intents_teacher/production_20000_questions.jsonl \
  --out dados/intents_teacher/production_20000 \
  --limit 20000 --batch-size 8 --workers 8
```

Isto prevê 2.500 lotes de 8 perguntas. Os 250 primeiros lotes concluídos são
reutilizados. O modelo predefinido é `gpt-6-luna`, com raciocínio `low`, via
Codex CLI autenticado na conta ChatGPT. Não é necessária chave da API.

## 3. Falhas e recuperação

- Interromper e inspecionar `batches/batch_*.error.txt` em caso de erros ou quota.
- O programa preserva lotes completos e não repete automaticamente chamadas
  que deixaram eventos mas não produziram um ficheiro válido.
- Primeiro testar `--recover-events` com os mesmos argumentos para recuperar
  respostas de eventos. Usar `--retry-errors` só quando uma repetição for
  explicitamente pretendida e a quota o permitir.
- Não mudar a ordem do ficheiro de entrada nem alterar o tamanho dos lotes
  dentro da mesma pasta de resultados.

O agregado final ficará em
`dados/intents_teacher/production_20000/teacher_intents_unverified.jsonl`.

## Depois da geração

Auditar uma amostra humana com especial atenção a `quantity/get`,
`ingredients/check`, `steps/explain`, `unknown` e avisos `taxonomy_warning`.
Não utilizar diretamente como treino definitivo. Antes do refinamento do
TinySLM, deduplicar paráfrases, controlar fuga entre receitas e construir
um conjunto de avaliação humana independente.
