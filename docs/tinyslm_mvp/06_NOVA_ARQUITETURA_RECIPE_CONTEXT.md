# TinySLM — decisão arquitetural: treinar o modelo para chamar ferramentas

**Decisão aprovada em 23/11/2026.** Substitui a estratégia de tentar resolver semanticamente perguntas C2 dentro de `RECIPE_SEARCH` (V1/V2) por um percurso supervisionado **TinySLM → RECIPE_CONTEXT → TinySLM**. Preservar V1/V2 e respetivos relatórios como experiências históricas; não os utilizar como gerador automático de evidências certificadas.

## Porque mudámos

- Treino de intenções v09 não ensinava o ciclo real chamada/resultado/resposta.
- Piloto v11 teve falhas severas de decisão/resposta.
- O corpus histórico tem 18.230 perguntas C1 e 18.559 C2. No conjunto candidato da etapa 3, 18.222 C1 e 18.524 C2 possuem citação literal, mas **respostas de teacher e parsing não estão certificados**.
- RECIPE_SEARCH V1/V2 aumentou a recuperação lexical de evidências, mas a revisão assistida de 100 casos deliberadamente difíceis encontrou apenas 12 pedidos integralmente satisfeitos; o problema principal está na seleção/semântica e não na consulta à SQLite.
- Decidimos que o **modelo interpreta a pergunta**; a ferramenta **não a interpreta** nem decide que informação é pertinente: devolve os dados reais da secção pedida.

## Contrato R2 atualizado

A aplicação já conhece o `recipe_id` e **não o solicita ao LLM**. O LLM só produz uma chamada permitida, por exemplo:

```text
CALL TOOL
NAME: RECIPE_CONTEXT
SECTION: PREPARATION
CHUNK: 1
```

A aplicação valida o nome e os campos (secção permitida e número de bloco), associa o seu `recipe_id` e chama `recipe_context.py`. O LLM **nunca escreve SQL**. Secções disponíveis: `DESCRIPTION`, `INGREDIENTS`, `PREPARATION` e `FULL`. `FULL` é possível mas tem maior custo de contexto; privilegiar a secção relevante.

A ferramenta devolve uma página do texto de origem, sem classificador, BM25 ou inferência de ingredientes:

```text
TOOL RESULT
NAME: RECIPE_CONTEXT
STATUS: FOUND
SECTION: PREPARATION
RECIPE: Bolo de iogurte
CHUNK: 1/1
HAS_MORE: NO
CONTENT:
SEGMENT 1: Bater os ovos com o açúcar.
SEGMENT 2: Adicionar o iogurte.
```

**Exemplo pedagógico fictício:** a saída acima é apenas demonstração; não foi extraída do corpus real de receitas em inglês.

`STATUS: FOUND` significa apenas que existem dados da secção, **não que a resposta à pergunta esteja nesse texto**. Outros estados: `NOT_FOUND` (receita), `EMPTY` (secção sem texto), `CHUNK_NOT_FOUND` (bloco fora do intervalo).

`SOURCE_WARNINGS` apresenta avisos do parser. Ingredientes com delimitadores não reconstruíveis são devolvidos na forma original, sem fingir que a lista foi analisada com sucesso. A preparação contém **segmentos heurísticos**, não passos culinários certificados.

### Limite de contexto

O checkpoint atual tem contexto de cerca de 512 tokens. A ferramenta pagina **sem perda de texto** em blocos de caracteres com tamanho configurável; não assume que caracteres = tokens. Antes de inferência, a aplicação precisa de aplicar o tokenizer real a **todo o prompt** e ajustar o tamanho do bloco para caber, incluindo pergunta, historial, cabeçalhos, chamada e resultado. Se um bloco não couber, deve ser pedido um bloco mais pequeno; nunca truncar a evidência silenciosamente.

Para receitas extensas, treinar exemplos com `CHUNK: 2`, `CHUNK: 3` e compreensão de `HAS_MORE`. **Ainda não está demonstrado** que o modelo de 51M consegue sintetizar várias páginas com fiabilidade; isso será um critério de avaliação.

## Desenho do treino — não confundir capability com decisão

**A decisão CALL TOOL depende da informação disponível, não do rótulo C1/C2.** Com contexto suficiente, uma pergunta histórica C2 pode ser respondida diretamente. Com contexto insuficiente, um exemplo historicamente C1 pode também precisar de ferramenta. Necessitamos de construir exemplos realistas dessas duas condições.

**A. Resposta direta (evidência no prompt):**

```text
RECIPE: Bolo de iogurte
EVIDENCE: Bater os ovos com o açúcar.
QUESTION: Quando adiciono o açúcar?
ANSWER: No primeiro passo, juntamente com os ovos.
```

**B. Aprender a escolher e pedir ferramenta (sem resposta no prompt):**

```text
RECIPE: Bolo de iogurte
DETAILS: Not provided.
QUESTION: Quando adiciono o açúcar?
CALL TOOL
NAME: RECIPE_CONTEXT
SECTION: PREPARATION
CHUNK: 1
```

**C. Aprender a responder depois do resultado real:**

```text
RECIPE: Bolo de iogurte
QUESTION: Quando adiciono o açúcar?
TOOL RESULT
NAME: RECIPE_CONTEXT
STATUS: FOUND
SECTION: PREPARATION
RECIPE: Bolo de iogurte
CHUNK: 1/1
HAS_MORE: NO
CONTENT:
SEGMENT 1: Bater os ovos com o açúcar.
SEGMENT 2: Adicionar o iogurte.
ANSWER: O açúcar é adicionado no primeiro passo, juntamente com os ovos.
```

Estes exemplos ilustram a estrutura, **não são dados históricos validados**. Usar as respostas reais geradas por `RECIPE_CONTEXT` a partir da SQLite, nunca resultados inventados.

Também são necessários exemplos `EMPTY`, `NOT_FOUND`, insuficiência da informação apesar de secção presente, pedidos de bloco seguinte, perguntas com exclusões, listas, perguntas compostas e pedidos fora do domínio.

## Etapas revistas e condições

1. **Etapa 5 (nova):** implementar ferramenta determinística `RECIPE_CONTEXT` em SQLite, testar sobre receitas reais e deixar V1/V2 arquivadas. **Concluída como implementação inicial; aprovar comportamento do modelo só após treino/teste**.
2. **Etapa 6:** congelar gramática das chamadas e do dispatcher da aplicação; medir tokens com tokenizer real e simular conversas completas, incluindo paginação, respostas sem evidência e falhas seguras.
3. **Etapa 7:** transformar o dataset histórico completo C1/C2 em episódios supervisionados com resultados reais da ferramenta, splits por receita e validação factual; gerar três tipos de exemplos (direto, chamada, pós-chamada), avaliar leakage, balanceamento e contagem de tokens. Não promover automaticamente respostas de teacher a verdade.
4. **Etapa 8:** treino massivo no Kaggle a partir do checkpoint escolhido, com preservação C1 e avaliação de tool use; **ainda não iniciado**.

Após o treino seguem avaliação funcional (etapa 9) e decisão para expandir a C3–C7 (etapa 10).

## Execução da ferramenta

Na raiz do projeto, com a SQLite descarregada **separadamente** do GitHub:

```bash
python tools/tinyslm_mvp/recipe_context.py \
  --db /caminho/recipes_normalized.sqlite \
  --recipe-id 'recipe_nlg_lite:00187d20-040d-45a3-984b-7de4a58f5b22' \
  --section INGREDIENTS --chunk 1

python -m unittest discover -s tools/tinyslm_mvp -p 'test_*.py' -v
```

A ferramenta usa apenas Python padrão e abre SQLite em modo leitura. Ainda **não** existe dispatcher do modelo nem novo treino.