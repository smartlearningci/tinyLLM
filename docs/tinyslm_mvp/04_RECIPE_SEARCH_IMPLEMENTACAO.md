# TinySLM — etapa 4: `RECIPE_SEARCH` (implementação base)

Data: 23/11/2026. **Implementação inicial funcional, NÃO validada para treino.**

## Objetivo e fronteiras

A aplicação conhece sempre `recipe_id`. O TinySLM **não gera SQL** e não recebe as 5.025 receitas. Quando precisa de contexto, gera apenas:

```text
CALL TOOL
NAME: RECIPE_SEARCH
QUERY: When should I put the rub in a shaker?
```

O programa obtém os ingredientes e passos **da receita indicada** usando `SELECT ... WHERE recipe_id=?` (SQLite somente leitura). Pesquisa todas as passagens dessa receita em memória e devolve **evidências copiadas da fonte**, nunca uma resposta gerada. O índice primário existente na SQLite basta; não é necessário criar FTS global, procurar receitas nem pagar APIs externas.

### Implementação `tools/recipe_search.py`

1. Validar o `recipe_id` da sessão e a query (a aplicação fornece o primeiro; não confiar no nome de receita escrito pelo modelo).
2. `SELECT` parametrizado das duas tabelas `ingredients` e `preparation_segments`, indexadas por receita, preservando `section`, `position` e texto original.
3. Retirar palavras funcionais e calcular ranking **BM25 lexical + similaridade de trigramas de caracteres** nas passagens da receita (CPU, sem dependências extra). Sem classificação de C1/C2 no SQL.
4. Escolher até quatro excertos e devolver proveniência: `ingredients:N` ou `preparation:N`.
5. Nunca inventar resultado. Se não houver correspondência lexical, devolver `INSUFFICIENT_EVIDENCE`.

O estado inicial é `EVIDENCE_CANDIDATES` **e não `FOUND`**, porque encontrar palavras semelhantes não prova relevância nem suficiência. O protocolo definitivo `FOUND / INSUFFICIENT_EVIDENCE` só será fechado após a etapa 5. Não utilizar esta versão para gerar automaticamente exemplos SFT aprovados.

Exemplo observado em receita real `smokehouse rub`:

```text
TOOL RESULT
STATUS: EVIDENCE_CANDIDATES
EVIDENCE:
PREPARATION 2: put the prepared rub in a shaker for applying.
```

Para «What quantity of paprika do I need?», encontrou `INGREDIENTS 1: 0.2 cup paprika`.

## Diagnóstico em 1.827 exemplos C2 do split de teste (por receita)

| Verificação | Resultado |
|---|---:|
| Cenários C2 do teste | 1.827 |
| Pelo menos um excerto lexical recuperado | 1.676 (91,7%) |
| Sem evidência lexical recuperável | 151 (8,3%) |
| Sobreposição lexical >=50% com alguma citação histórica | 62,34% |
| Sobreposição lexical >=80% com alguma citação histórica | 45,43% |

**Estas percentagens NÃO medem correção semântica.** As citações históricas são referências não certificadas, podem atravessar vários segmentos e misturar ingredientes e preparação. Métrica implementada por interseção de termos das citações com os termos dos excertos devolvidos. Uma resposta correta pode não atingir o limiar e um excerto errado pode atingi-lo. Ver diagnóstico `stage4_retrieval_diagnostics.json`.

### Falha importante observada

Na receita `smokehouse rub`:

- Pergunta: `Which dry seasonings are listed, not the sugars?`
- Resultado lexical: `0.5 cup brown sugar` e `0.5 cup white sugar`.

A ferramenta encontra um termo, mas **não entende a negação**. É exatamente o tipo de erro que devemos eliminar **antes** do novo treino; não se podem promover os excertos a `FOUND` só porque foram encontrados. Na receita `jamaican red beans and rice`, a recuperação da primeira etapa de sauté também não foi suficientemente completa. Perguntas compostas e sequências exigem recuperação de várias passagens relevantes.

## Etapa 5: como melhorar e avaliar

- Construir um conjunto de referência independente de exemplos C2 com passagens alvo **manualmente validadas** e casos de ausência, negação, seleção múltipla, parafraseamento e sequência temporal.
- Comparar uma versão de recuperação com **classificador leve** (`TF-IDF + LogisticRegression`) de secção + reordenação/ranking, usando apenas exemplos de treino; as citações do teacher podem gerar rótulos fracos sujeitos a revisão.
- Testar expansão para passos adjacentes, pedidos de lista e perguntas compostas quando justificado pelos erros, não com regras casuísticas ad hoc.
- Medir a qualidade da ferramenta: recall@k, precisão@k, cobertura de todas as evidências necessárias, abstenção correta e latência, tudo **com split por receita**.
- Definir um limiar de confiança validado para distinguir `FOUND`, `AMBIGUOUS` e `INSUFFICIENT_EVIDENCE`; só depois preparar as respostas reais de C2 para treino.
- Confirmar limites de 512 tokens com o tokenizer real e evitar cortar passagens de forma silenciosa.

## Execução local

Na raiz de `tinyLLM`, depois de obter `recipes_normalized.sqlite` do pacote de dados da etapa 1–3:

```bash
python tools/tinyslm_mvp/recipe_search.py \
  --db /caminho/para/recipes_normalized.sqlite \
  --recipe-id 'recipe_nlg_lite:...' \
  --query 'When should I put the rub in a shaker?'
```

Testes unitários (sem rede nem GPU):

```bash
python -m unittest discover -s tools/tinyslm_mvp -p 'test_recipe_search.py' -v
```

Repetir diagnóstico separado por receita:

```bash
python tools/tinyslm_mvp/evaluate_retrieval_baseline.py \
  --db /caminho/para/recipes_normalized.sqlite \
  --candidates /caminho/para/c2_candidates.jsonl.gz \
  --split test --out stage4_retrieval_diagnostics.json
```

**Estado:** etapa 4 concluída como baseline implementada e testada; **não** como ferramenta aprovada para treino. Próxima etapa 5: aferir, corrigir e validar recuperação C2. Nenhum fine-tuning foi iniciado.