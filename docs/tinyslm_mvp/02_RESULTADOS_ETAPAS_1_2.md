# TinySLM MVP — resultados reais das etapas 1 e 2

Execução: 22/11/2026. Script reproduzível:
`tools/tinyslm_mvp/normalize_audit_recipes.py`.

## Etapa 1 — normalização

- Fonte usada: `intent_mvp_v03_en/recipes.sqlite` (exportação local
  `recipe_nlg_lite`, **em inglês**).
- **5.025/5.025 receitas disponíveis normalizadas** para um texto de secções
  invariáveis: `RECIPE`, `TITLE`, `DESCRIPTION`, `INGREDIENTS`, `PREPARATION`.
- **45.456 entradas de ingredientes** e **58.021 segmentos de preparação**
  gerados heurísticamente; os segmentos não são passos certificados.
- Cada receita conserva `recipe_id`, `source_id`, texto original integral,
  ingredientes e preparação originais. **Zero alterações nos campos originais**
  na comparação SQLite de todas as 5.025 receitas.
- Zero identificadores repetidos; zero títulos duplicados adicionais.
- Artefacto integral: `resultados/recipes_normalized.jsonl.gz` (4,6 MB),
  acompanhado da SQLite normalizada local (54 MB). Estes **dados não entram
  no Git** pela política do projeto; são gerados pelo comando abaixo e
  podem ser distribuídos como dataset separado.

## Etapa 2 — auditoria

| Critério | Resultado |
| --- | ---: |
| Receitas de origem disponíveis | 5.025 |
| Receitas com originais preservados | **5.025** |
| IDs repetidos | **0** |
| Receitas com aviso(s) de revisão | **3.248** |
| Ingredientes com vírgulas ambíguas | 4.879 entradas |
| Receitas com pelo menos uma vírgula ambígua | 2.997 |
| Receitas com ingrediente sem quantidade inicial | 391 |
| Receitas com separadores que não se recompõem | 64 |
| Receitas com mais de 30 segmentos | 162 |
| Receitas com menos de 2 segmentos | 205 |
| Ingredientes não analisáveis pela regra de quantidade | 296 entradas |
| Excertos originais alterados durante exportação | **0** |
| Receitas com aprovação humana para treino | **0** |

O alerta de vírgulas **não é um erro factual confirmado**. Pode tratar-se de
vírgulas legítimas no nome do ingrediente; a análise não pode escolher entre
as hipóteses sem consultar o original. Em 64 casos, o texto original tem
separadores irregulares (por exemplo `, ,`): o formato textual apresenta a
frase original inteira de ingredientes, preservando o conteúdo, e marca
revisão pendente. As 3.248 receitas com avisos **não foram excluídas nem
aprovadas**.

Comprimento textual aproximado, contado por **palavras, não pelo tokenizer**:
mediana 217; percentil 90 de 428; percentil 99 de 830; máximo de 2.035.
São **281 receitas com mais de 512 palavras** (e 890 com mais de 350):
um modelo limitado a 512 tokens exige seleção de contexto e contagem
com o seu tokenizer real antes do treino.

## Questão pendente do catálogo histórico

O projeto menciona **5.108 receitas em `dados/queue.sqlite`**, uma base
histórica de destilação **não presente nesta cópia de trabalho**. A origem
agora auditada é outra SQLite, com 5.025 receitas. A diferença aritmética
é 83, mas **não há prova de que sejam exatamente 83 IDs em falta**: os
catálogos ainda não foram comparados. Só após receber a `queue.sqlite` ou
o export de receitas correspondente poderemos fazer a reconciliação de IDs
e normalizar os registos adicionais, se existirem.

## Reproduzir em Linux/macOS/Windows com Python 3.10+

Na raiz do repositório:

```bash
python tools/tinyslm_mvp/normalize_audit_recipes.py \
  --source /caminho/para/recipes.sqlite \
  --output /caminho/para/novo_resultado
python -m unittest discover -s tools/tinyslm_mvp -p 'test_*.py' -v
```

O script usa apenas a biblioteca padrão, abre a base de origem no modo
`read-only` e não substitui outputs já existentes. Guarda:

- `recipes_normalized.jsonl.gz` — todas as receitas e originais;
- `recipes_normalized.sqlite` — consulta estruturada para a aplicação;
- `review_queue.jsonl.gz` — casos a rever e informação original;
- `audit_report.json` — contagens e hash SHA-256 da fonte;
- `examples.md` — exemplos reais para conferência.

Nesta entrega, o relatório e os exemplos **sem dados massivos** estão
disponíveis em `resultados/` e são versionados no repositório.

## Estado e próxima decisão

**Concluído:** normalização de toda a fonte local e auditoria automatizada
de integridade. **Não concluído:** revisão factual/semântica de 3.248 casos
e reconciliação com a origem histórica de 5.108 receitas. Não foi iniciado
o treino, nem a etapa 3 das perguntas C1/C2.

Na etapa 3 iremos aproveitar **todas as perguntas e respostas históricas
C1 e C2**, mas só promover ao treino exemplos cujas evidências sejam
verificadas. C1 continuará a resposta direta; C2 deverá produzir a chamada
`CALL TOOL / NAME: RECIPE_SEARCH / QUERY: ...` e, depois de receber o
resultado real, uma resposta fiel à receita e à pergunta.
