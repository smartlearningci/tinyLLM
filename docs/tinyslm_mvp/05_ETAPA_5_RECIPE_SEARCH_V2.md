# TinySLM MVP — Etapa 5: melhoria e avaliação da RECIPE_SEARCH

Data: 23/11/2026. **Estado: desenvolvimento e diagnóstico concluídos; aceitação funcional ainda NÃO alcançada.** Não foi iniciado fine-tuning. Baseline da etapa 4 (`recipe_search.py`) permanece inalterada; a versão de avaliação é `recipe_search_v2.py`.

## Porque é necessária esta etapa

A ferramenta inicial fazia BM25/cosseno sobre os ingredientes e segmentos da receita conhecida (`recipe_id`). No teste de 1.827 perguntas C2, a coincidência lexical de >=80% com citações históricas foi 45,43%. Uma pergunta da receita real `smokehouse rub` pedia os temperos secos **excluindo açúcares**, mas o ranking devolvia açúcares. A recuperação de passagens, por si só, não é compreensão semântica.

## Implementação V2

1. **Conservação de dados e segurança:** SQLite aberto `read-only`, consultas com `?`; `recipe_id` fornecido pela aplicação, nunca pelo SQL gerado pelo modelo; os excertos são originais, com `section`, `position`, `parse_status` e `source_ref`.
2. **Encaminhamento:** regras explícitas para ingredientes/quantidades, preparação/sequência e pedidos mistos; um router TF-IDF + Logistic Regression pode ser treinado a partir dos **exemplos C2 `train`** e usado opcionalmente para um *boost* suave. Não decide sozinho nem substitui restrições.
3. **Entidades e exclusões:** correspondência com nomes dos ingredientes e uma taxonomia pequena e conservadora para temperos e açúcares. Identifica padrões como `not the sugars` e `excluindo açúcar`. A taxonomia **não é completa**; o resultado não certifica ausência de alergénios, nem listas exaustivas.
4. **Ranking e recuperação:** BM25 + cosseno de trigramas; recuperação de múltiplos elementos e algum contexto anterior para perguntas temporais. Saída sujeita a máximo de excertos e orçamento de caracteres; `truncated=true` e `WARNING: INCOMPLETE_RESULTS` quando há corte.
5. **Português vs fonte inglesa:** pequeno léxico determinístico de equivalências (por exemplo `açúcar→sugar`, `farinha→flour` e `momento→when`). Resolve casos comuns, **não** uma pesquisa bilingue geral nem todas as paráfrases.
6. **Confiança:** todos os excertos são `STATUS: EVIDENCE_CANDIDATES`, nunca `FOUND` certificado; resultados em falta dão `INSUFFICIENT_EVIDENCE`. A resposta não é gerada pela ferramenta.

### Exemplo real

Receita `smokehouse rub`; pergunta: `I’m gathering only the dry seasonings, not the sugars. Which listed ingredients should I set out?`

A V2 devolve **paprika, onion powder, ground rosemary, garlic powder, black pepper, ginger powder, cayenne pepper** (7 ingredientes), **sem brown sugar e white sugar**. O resultado tem `WARNING: REVIEW_REQUIRED`, pois a classificação de temperos por léxico pode ser incompleta.

### Exemplo PT-PT (teste sintético sobre receita em inglês)

Pergunta: `Em que momento adiciono o açúcar?` → `PREPARATION 1: Beat the eggs with sugar.` com a equivalência lexical `açúcar→sugar`. É um teste do contrato, **não** um teste de tradução geral nem de resposta final em português.

## Resultados empíricos de recuperação

Métrica: **sobreposição de tokens entre excertos recuperados e as citações do teacher**. Citações não são verdade certificada e vários excertos podem aumentar esta métrica sem melhorar a precisão. Os conjuntos `validation` e `test` foram separados por `recipe_id` **nesta exportação**; a base histórica do checkpoint não está totalmente auditada quanto a possíveis exposições anteriores.

| Métrica | Validação (1.815) — V1 | Validação — V2 | Teste (1.827) — V1 | Teste — V2 |
|---|---:|---:|---:|---:|
| Sobreposição >=50% | 61,60% | **70,85%** | 62,34% | **73,34%** |
| Sobreposição >=80% | 43,80% | **54,21%** | 45,43% | **57,47%** |
| Sobreposição média | 61,68% | 68,98% | 62,19% | 70,78% |
| Excertos por pergunta | 2,91 | 4,18 | 2,98 | 4,32 |
| Perguntas sem candidato | 162 | 159 | 151 | 151 |
| Perguntas V2 com resultado truncado | — | 276 | — | **262** |

**O classificador opcional não melhorou significativamente estes resultados:** no teste, a V2 com router teve 57,36% de sobreposição >=80%, vs. 57,47% sem router. Por isso o motor V2 **não carrega nem requer** este modelo por omissão. Se for usado, será necessário verificar que melhora a qualidade numa avaliação humana, não apenas nos rótulos fracos.

Treino do router: 14.317 exemplos com rótulos automáticos derivados da localização das citações na receita; validação 1.743. Acordo com os rótulos fracos na validação: **75,67%**. Não equivale a reconhecer corretamente a intenção nem a encontrar evidência suficiente.

## Avaliação humana pendente

Foi criada a amostra `manual_review_100.jsonl` com **100 casos não pontuados**: 20 melhorias lexicais, 20 regressões, 20 resultados truncados, 20 sem candidatos e 20 casos gerais. Cada caso tem pergunta, citações históricas (referência fraca), excertos V1 e V2 e campos `human_evidence_correct`, `human_evidence_complete` e `human_contradiction_or_exclusion`, inicialmente `null`. Estes dados específicos estão no pacote de trabalho, **não publicados no Git**.

A meta >=90% de recuperação factual **não foi demonstrada**. A V2 ainda não resolve de modo fiável perguntas de raciocínio, negadas, compostas, com sinónimos distantes, com tradução livre, com dependências entre muitos passos, nem todos os casos ambíguos das 3.248 receitas com avisos de normalização. O limite de contexto do TinySLM (~512 tokens) exige testes com tokenizer real, não apenas limite de caracteres.

**Próxima ação dentro da etapa 5:** rever manualmente a amostra, classificar erros por causa (recuperação, parsing, contexto, pergunta composta, tradução), corrigir e repetir a avaliação. Não passar à etapa 6/7 como se a ferramenta estivesse certificada.

## Execução local — depois de `git pull`

Extrair o pacote da etapa 3 para uma pasta de dados no PC. Usar os caminhos efetivos da extração nos comandos seguintes. Não é necessário instalar scikit-learn para executar a ferramenta V2.

```bash
python tools/tinyslm_mvp/recipe_search_v2.py \
  --db /caminho/recipes_normalized.sqlite \
  --recipe-id 'recipe_nlg_lite:6cf04033-ad68-4b32-b94e-ea8639012a7a' \
  --query 'I am gathering only the dry seasonings, not the sugars. Which listed ingredients should I set out?'

python tools/tinyslm_mvp/evaluate_retrieval_v2.py \
  --db /caminho/recipes_normalized.sqlite \
  --candidates /caminho/c2_candidates.jsonl.gz \
  --split test --out retrieval_v2_test.json

python tools/tinyslm_mvp/sample_manual_review.py \
  --db /caminho/recipes_normalized.sqlite \
  --candidates /caminho/c2_candidates.jsonl.gz \
  --out manual_review_100.jsonl

python -m unittest discover -s tools/tinyslm_mvp -p 'test_*.py' -v
```

Para reproduzir **opcionalmente** o router (este treino exige `scikit-learn`, mas a pesquisa V2 não):

```bash
python tools/tinyslm_mvp/train_section_router.py \
  --db /caminho/recipes_normalized.sqlite \
  --candidates /caminho/c2_candidates.jsonl.gz \
  --model-out section_router_v1.json \
  --report-out section_router_v1_report.json
```

A execução do router pré-treinado é opcional via `--router section_router_v1.json`.

## Artefactos

- Código: `tools/tinyslm_mvp/recipe_search_v2.py`, `train_section_router.py`, `evaluate_retrieval_v2.py`, `sample_manual_review.py`.
- Testes: `tools/tinyslm_mvp/test_recipe_search_v2.py` (8 novos testes). **20 testes no total** executados sobre a estrutura completa do projeto; passaram, incluindo os 12 anteriores.
- Métricas agregadas: `docs/tinyslm_mvp/resultados/stage5_retrieval_validation.json`, `stage5_retrieval_test.json` e `stage5_router_training_report.json`.
- **Não colocar os milhares de receitas nem as perguntas completas no Git público.**