# TinySLM MVP — Etapa 3: reaproveitamento dos diálogos C1/C2

Data: 23/11/2026. **Etapa 3 terminada como preparação e auditoria de candidatos; NÃO como aprovação para treino.**

## Origem e critérios

- Foram percorridas **138.794** linhas do histórico `train.jsonl` recebido; seleção **C1 = 18.230** e **C2 = 18.559**.
- Cada exemplo conserva o `recipe_id`, a pergunta, a conversa original, a resposta histórica do professor e as citações.
- A receita é ligada à SQLite `recipes_normalized.sqlite` (5.025 receitas) de R1/R2.
- As citações têm de existir literalmente em `original_text` da receita, com `source_id` correspondente.
- Sem revisão humana, uma citação literal **não é prova de resposta correta**. Todos os exemplos têm `training_approved=false`.
- As receitas são atribuídas a treino/validação/teste de modo estável por SHA-256 do `recipe_id`; não há sobreposição de IDs de receita **entre estes três conjuntos**.
- O histórico aqui usado chama-se `train.jsonl` e pode ter sido utilizado em treinos anteriores. Portanto o novo conjunto de teste **não é garantidamente independente dos checkpoints antigos**. Para teste real de generalização, reservar futuramente receitas nunca antes usadas.

## Resultados de execução

| Estado | C1 | C2 | Total |
| --- | ---: | ---: | ---: |
| Históricos | 18.230 | 18.559 | 36.789 |
| Candidatos com citação literal | **18.222** | **18.524** | **36.746** |
| Citação divergente da fonte | 8 | 35 | 43 |
| Candidatos com aviso de normalização | 11.747 | 11.942 | 23.689 |
| Candidatos sem aviso automático | 6.475 | 6.582 | 13.057 |

Os avisos são indicadores de revisão, não erros semânticos confirmados. Os 13.057 sem aviso também não são automaticamente aprovados. Estes valores substituem a contagem preliminar de 36.684 candidatos / 105 casos sinalizados, pois foram recalculados com o **ficheiro histórico e a SQLite normalizada efetivamente disponíveis** e com uma regra de citação literal reproduzível; a diferença deve ser reconciliada se forem usados outros filtros.

### Separação por receita (candidatos)

| Conjunto | C1 | C2 | Total |
| --- | ---: | ---: | ---: |
| Treino | 14.650 | 14.882 | 29.532 |
| Validação | 1.800 | 1.815 | 3.615 |
| Teste | 1.772 | 1.827 | 3.599 |

Existem 5.025 IDs de receita distintos no conjunto de candidatos.

## Como preparar C1 e C2

**C1 — sem ferramenta.** A informação explícita necessária deve estar no contexto. O conjunto inclui `candidate_decision_context` com a citação disponível. A resposta histórica é candidata e será revista.

Exemplo observado (lemon and orange chicken):

```text
RECIPE
TITLE: lemon and orange chicken
EVIDENCE FROM RECIPE:
- 0.5 teaspoon salsa macha
QUESTION: I want to keep the chicken mildly seasoned. How much salsa macha does this recipe list?
ANSWER (teacher, não validada): It lists 0.5 teaspoon of salsa macha.
```

**C2 — com ferramenta.** A aplicação conhece a receita. Antes de consultar, o contexto contém título, mas não a informação necessária. O modelo aprende a pedir a recuperação; **não recebe a receita integral simultaneamente com uma etiqueta `CALL TOOL`**, senão aprenderia a solicitar ferramentas desnecessárias.

Exemplo observado (braised lamb shanks):

```text
RECIPE
TITLE: braised lamb shanks
DETAILS: Not present in the supplied context.
QUESTION: I want to know when the sweet potatoes go in. Which ingredients should I hold back until that point?
CALL TOOL
NAME: RECIPE_SEARCH
QUERY: I want to know when the sweet potatoes go in. Which ingredients should I hold back until that point?
```

O resultado real de `RECIPE_SEARCH` ainda não está disponível/validado e por isso o campo `tool_result_status` está em `PENDING_REAL_TOOL_EVALUATION`. Não foram inventados resultados da ferramenta. Depois da etapa 4/5, serão criados exemplos de **segunda passagem**: receita + pergunta + evidência realmente recuperada → resposta fundamentada.

A decisão tem de depender da **presença da informação no contexto**, não de uma regra fixa por competência. No dataset definitivo da etapa 7, geraremos pares controlados com a mesma pergunta e contexto suficiente/insuficiente, de modo que também casos C2 possam responder sem ferramenta quando têm prova disponível.

## Entregáveis e execução

`tools/tinyslm_mvp/build_c1_c2.py` aceita:

```bash
python tools/tinyslm_mvp/build_c1_c2.py \
  --dialogues /caminho/train.jsonl \
  --recipes /caminho/recipes_normalized.sqlite \
  --out /caminho/etapa3
```

Produz `c1_candidates.jsonl.gz`, `c2_candidates.jsonl.gz`, `review_queue.jsonl.gz` e `stage3_report.json`. Não substitui saídas antigas nem chama o Codex. Os dados massivos são distribuídos em pacote separado, não guardados no Git.

## Estado e próximas etapas

Etapa 3 concluída **como preparação dos candidatos**. Ainda não foi aprovado qualquer exemplo para treino. Antes de iniciar o fine-tuning (etapa 8), faltam quatro etapas:

4. Implementar o recuperador `RECIPE_SEARCH` em CPU sobre a receita conhecida.
5. Avaliá-lo, especialmente em C2 e nas perguntas livres.
6. Congelar e testar o protocolo textual `CALL TOOL / TOOL RESULT / ANSWER`.
7. Produzir o dataset final, com decisões *tool/direct* condicionadas pelo contexto e respostas posteriores a resultados reais das ferramentas.

**Bloqueios:** auditoria das respostas históricas, avisos de normalização e limite de 512 tokens; qualidade de recuperação da ferramenta ainda não demonstrada. Começar treino só com exemplos verificados e splits apropriados.