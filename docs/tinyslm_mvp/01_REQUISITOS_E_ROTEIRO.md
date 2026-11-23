# TinySLM MVP — requisitos e sequência de trabalho

Estado: decidido em 22/11/2026. Trabalhar **uma etapa de cada vez**;
apresentar resultados antes de avançar. Não executar fine-tuning nesta fase.

> **ATUALIZAÇÃO DE ARQUITETURA — 23/11/2026:** as secções antigas **R2/R4** sobre `RECIPE_SEARCH` e TF-IDF estão **substituídas** pela decisão documentada em [06_NOVA_ARQUITETURA_RECIPE_CONTEXT.md](06_NOVA_ARQUITETURA_RECIPE_CONTEXT.md). O modelo passa a escolher `RECIPE_CONTEXT` + `SECTION` + `CHUNK`, a ferramenta devolve apenas texto real da SQLite. As V1/V2 são histórico. Manter este documento para rastrear a evolução.

## Contratos fechados (versão histórica, exceto R1/R3/R5)

**R1 — Receitas:** todas as receitas da fonte de treino numa estrutura textual
fixa, legível, sem JSON no contexto do TinySLM. Manter os campos título,
descrição, ingredientes, quantidades tal como constam da fonte e preparação.
Separar dados originais de interpretações heurísticas, preservar ID e fonte.
Não inventar valores em falta. Não ocultar receitas com erros de parsing.

**R2 — Ferramentas:** protocolo textual curto, sem pedir ao modelo o código
da competência (C1/C2 etc.). A aplicação já conhece `recipe_id`. Exemplo:

```text
CALL TOOL
NAME: RECIPE_SEARCH
QUERY: Em que momento adiciono o açúcar?
```

Retorno esperado da aplicação, **apenas se a evidência existir**:

```text
TOOL RESULT
STATUS: FOUND
EVIDENCE:
Preparação, segmento 1: Bater os ovos com o açúcar.
```

Em caso de dúvida ou falta de prova: `STATUS: INSUFFICIENT_EVIDENCE`.
O TinySLM aprende a responder diretamente ou a pedir uma ferramenta;
**não gera SQL** e **não precisa de declarar C1/C2**. A aplicação valida,
executa e devolve o resultado.

**Regra de contexto:** a receita é sempre conhecida da aplicação, mas o
contexto disponível ao TinySLM pode conter apenas partes selecionadas para
respeitar 512 tokens. A decisão de não chamar ferramenta é segura apenas
quando há evidência suficiente no contexto fornecido.

**R3 — C1 e C2:** usar todas as perguntas/respostas históricas pertinentes,
preservando os splits por `recipe_id`; reparar/validar os dados, não promover
automaticamente toda a saída do teacher a verdade. C1 permanece diretamente
respondível; C2 gera chamada da ferramenta e, após receber **resultado real**,
responde estritamente com base na receita, pergunta e evidência.

**R4 — Pesquisa:** `RECIPE_SEARCH` opera sobre a receita conhecida. Para C2,
precisa identificar que informação se procura (por exemplo,
ingredientes/quantidades versus preparação) e que entidade é alvo (por
exemplo, açúcar). Experimentar classificador leve CPU TF-IDF + Logistic
Regression para a região, correspondência conservadora com ingredientes e
SQL por ID. Validar contra paráfrases reais; um `LIKE` isolado não resolve
interpretação semântica. FTS5/cosseno apenas se as provas justificarem.

**R5 — Falta de prova e segurança:** tool deve devolver ausência/ambiguidade;
modelo não infere ingredientes, alergénios, substituições ou outras respostas
não apoiadas. Testar perguntas fora do domínio separadamente.

## Ordem e critérios de saída

| Etapa | Trabalho | Evidência de conclusão |
| --- | --- | --- |
| 1 | Normalizar 100% das receitas **disponíveis**, sem perda de fonte | Dataset completo, esquema e exemplos reais |
| 2 | Auditar: integridade, distribuição, ambiguidades, 5.025 vs 5.108 | Relatório reproduzível + fila de revisão + lacunas explícitas |
| 3 | Reaproveitar perguntas/respostas históricas **C1/C2**, reconciliar referências | Splits por receita; respostas e citações verificadas |
| 4 | Construir `RECIPE_SEARCH` sobre a receita conhecida | **Baseline implementada** em CPU; evidência ainda não certificada (ver `04_RECIPE_SEARCH_IMPLEMENTACAO.md`) |
| 5 | Avaliar ferramenta isoladamente | **V2 implementada e diagnosticada**, mas sem aceitação factual: ver `05_ETAPA_5_RECIPE_SEARCH_V2.md`; revisão humana pendente |
| 6 | Congelar protocolo textual R2 e exemplos | Testes dos formatos, sem JSON no prompt |
| 7 | Produzir treino C1 direto + C2 pedir tool + C2 responder após tool | Dados massivos aprovados, sem leakage |
| 8 | Fine-tuning em checkpoint escolhido, com rehearsal C1 | Métricas por época, checkpoint e previsões |
| 9 | Medir decisão, pedido, evidência, resposta e OOD | Relatórios por competência e amostras de erros |
| 10 | Decisão go/no-go | Só alargar a C3–C7 se comprovado |

Metas de aceitação **propostas, por confirmar em avaliação**:
- decidir *tool* / *direct*: >= 90% em cada subconjunto;
- recuperar evidência correta C2: >= 90%;
- resposta C2 fundamentada: >= 80%;
- recusa sem evidência: >= 90%;
- não deteriorar C1 de forma significativa.

## Estado nesta entrega

- Etapas 1 e 2: executar scripts de normalização e auditoria, publicar
  artefactos e resultados reais, sem declarar os casos por rever como aceites.
- Etapa 3: **concluída como preparação de candidatos**. Foram auditadas 36.789 perguntas C1/C2; 36.746 possuem citação literal, 43 seguem para revisão. Ver `03_ETAPA_3_C1_C2.md`. Ainda não há respostas de ferramenta verificadas nem exemplos aprovados para treino.
