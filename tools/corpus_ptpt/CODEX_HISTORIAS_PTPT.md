# TinySLM-PTPT — adaptar 50 histórias e depois todas com Codex CLI

## Método recuperado da experiência inglesa

Este pipeline foi adaptado de [`tools/recipe_intents/codex_generate_intents.py`](../recipe_intents/codex_generate_intents.py) e da documentação [`PRODUCAO_20000_CODEX.md`](../recipe_intents/PRODUCAO_20000_CODEX.md): **Codex CLI autenticado com ChatGPT, sem chave API**, prompt curto, resposta JSON estruturada, lotes, 8 trabalhadores, raciocínio baixo, resultados por lote, retoma, recuperação de eventos e deteção de limites. O modelo predefinido (`gpt-6-luna`) é o que estava configurado no pipeline anterior; **se já não estiver disponível, é preciso escolher um modelo Codex suportado e começar numa pasta de execução nova**.

**Atenção:** 20.000 classificações de perguntas curtas e até ~180.000 histórias completas têm custos computacionais e limites de utilização muito diferentes. **Não está garantido** conseguir tudo em dois dias nem dentro do plafond anterior. Primeiro medimos o piloto de 50, consultamos os tokens e só depois damos ordem para aumentar o volume. Não abrir chamadas API pagas.

## Prompt que será enviado ao Codex

> Reescreve cada história infantil em português de Portugal (PT-PT). Mantém o enredo, as personagens, a simplicidade e aproximadamente o tamanho. Corrige vocabulário e construções brasileiras. Não resumas nem inventes. Devolve apenas JSON com responses (id, text_ptpt), mesmos IDs.

A cada pedido acrescenta-se um pequeno lote de histórias originais com os respetivos IDs. O schema JSON limita cada resposta a `id` e `text_ptpt`, evitando justificações que aumentariam consumo. Os conteúdos de origem ficam guardados **apenas localmente** e são enviados ao Codex quando o utilizador iniciar as chamadas.

## 1. Preparar fila definitiva e piloto (sem consumo Codex)

Na raiz do `tinyLLM`:

```bash
conda activate tinyslm-ptpt
git pull --ff-only
python -m unittest discover -s tools/corpus_ptpt -p 'test_*.py' -v
python tools/corpus_ptpt/codex_adapt_stories.py preparar
```

A fila `dados/corpus_ptpt/historias/codex/fila_v1.jsonl` é **imutável** e tem manifesto SHA-256. A primeira amostra é de **50 histórias retiradas de toda a coleção**, 30 do TinyStories e 20 do Boakpe, por seleção determinística. O restante corpus contém histórias únicas após deduplicação exata entre as origens. As histórias ainda estão em **PT-BR**; a fila é apenas uma entrada de trabalho.

Não voltar a executar `preparar` se a fila já existir; isto evita mudar a ordem ou gastar novamente quota em lotes conhecidos.

## 2. Simular o piloto, e depois fazer 50 adaptações reais

```bash
codex login status
python tools/corpus_ptpt/codex_adapt_stories.py gerar --limit 50 --dry-run
```

Se a conta ChatGPT estiver autenticada e a simulação estiver correta:

```bash
python tools/corpus_ptpt/codex_adapt_stories.py gerar --limit 50 \
  --batch-size 10 --workers 8 --reasoning low
```

**Exatamente cinco lotes**, cada um com dez histórias. O mesmo tamanho e modelo serão mantidos na produção. Usa-se o Codex CLI já autenticado, sem `OPENAI_API_KEY` ou `CODEX_API_KEY`.

O script guarda `run_config.json`, `batches/batch_000000.json`, `...events.jsonl` e métricas (`input_tokens`, `output_tokens`, tempo). Um lote com resultado válido não é repetido. Se o limite Codex for atingido, deixam de ser lançados novos pedidos, embora os que estejam em curso possam terminar.

Ver métricas e projeção linear (não equivale a quota financeira):

```bash
python tools/corpus_ptpt/codex_adapt_stories.py estado
```

## 3. Exportar, auditar e rever manualmente TODAS as 50

```bash
python tools/corpus_ptpt/codex_adapt_stories.py exportar --limit 50 \
  --out dados/corpus_ptpt/historias/adaptados/codex_piloto_50.jsonl.gz

python tools/corpus_ptpt/historias_ptpt.py auditar \
  --adaptados dados/corpus_ptpt/historias/adaptados/codex_piloto_50.jsonl.gz \
  --out dados/corpus_ptpt/historias/auditoria/codex_piloto_50.jsonl.gz

python tools/corpus_ptpt/historias_ptpt.py amostrar \
  --auditados dados/corpus_ptpt/historias/auditoria/codex_piloto_50.jsonl.gz \
  --csv dados/corpus_ptpt/historias/revisao/codex_piloto_50.csv --por-lote 50
```

Abrir o CSV e verificar **as 50 histórias**: pronome, sintaxe, vocabulário, enredo e naturalidade PT-PT. Os filtros são heurísticos e não dispensam esta revisão. Não aprovar automaticamente a coluna `aprovada`. Se as saídas forem fracas, não escalar; melhorar modelo/prompt **numa execução nova**.

## 4. Continuar para todas as histórias, sem gastar chamadas nos cinco lotes iniciais

Depois de validar o piloto:

```bash
python tools/corpus_ptpt/codex_adapt_stories.py gerar --limit 0 \
  --batch-size 10 --workers 8 --reasoning low --max-new-batches 1000
```

O programa começa no primeiro lote em falta, mantém o trabalho concluído e limita a **1000 chamadas novas por execução** (até 10.000 histórias). Para prosseguir, repetir exatamente o mesmo comando. Usar `--max-new-batches 0` **só se quiseres remover o teto local**; o serviço continua sujeito aos limites de uso ChatGPT/Codex.

Em caso de falha/limite de utilização:

```bash
python tools/corpus_ptpt/codex_adapt_stories.py gerar --limit 0 --recover-events
```

Isto tenta recuperar respostas completas dos eventos guardados **sem fazer chamadas novas**. Só usar `--retry-errors` depois de verificar os erros e confirmar que é apropriado consumir mais quota. **Não alterar a fila, `--batch-size`, `--model` ou `--reasoning` no meio da mesma execução.**

No fim da adaptação de todas as histórias:

```bash
python tools/corpus_ptpt/codex_adapt_stories.py exportar --limit 0 \
  --out dados/corpus_ptpt/historias/adaptados/codex_todas.jsonl.gz
```

Esta exportação falha se faltar algum lote: não publica um dataset incompleto como se estivesse pronto. Os textos ficam marcados `pending_audit` para os scripts existentes.

## 5. Auditoria e publicação do corpus PT-PT

```bash
python tools/corpus_ptpt/historias_ptpt.py auditar \
  --adaptados dados/corpus_ptpt/historias/adaptados/codex_todas.jsonl.gz \
  --out dados/corpus_ptpt/historias/auditoria/codex_todas.jsonl.gz

python tools/corpus_ptpt/historias_ptpt.py amostrar \
  --auditados dados/corpus_ptpt/historias/auditoria/codex_todas.jsonl.gz \
  --csv dados/corpus_ptpt/historias/revisao/codex_todas.csv --por-lote 20
```

Aprovar **manualmente** cada amostra no CSV. Uma amostra rejeitada bloqueia o lote inteiro. Só depois de preencher as aprovações:

```bash
python tools/corpus_ptpt/historias_ptpt.py publicar \
  --auditados dados/corpus_ptpt/historias/auditoria/codex_todas.jsonl.gz \
  --revisao dados/corpus_ptpt/historias/revisao/codex_todas.csv \
  --out-dir dados/corpus_ptpt/historias/aprovadas/codex
```

A etapa de publicação faz deduplicação exata e aproximada **entre as duas fontes** e cria `historias_train.jsonl.gz`/`historias_validation.jsonl.gz` em PT-PT. O objetivo é obter **100.000 histórias aceites**, não simplesmente 100.000 histórias traduzidas. Se o número for inferior, avaliar qualidade e recolher mais material, sem incluir PT-BR cru.

## Segurança, preservação e limitações

- **Sem API paga:** o comando recusa variáveis `OPENAI_API_KEY`/`CODEX_API_KEY` definidas e verifica `codex login status` da conta ChatGPT.
- **Retoma:** resultados concluídos são imutáveis e validados por hash de lote. Ficheiros de eventos e erros preservados; repetição de falhas só com pedido explícito.
- **Qualidade:** nenhuma tradução gerada pelo Codex é automaticamente uma história PT-PT aprovada; uso condicionado a auditoria automática e revisão.
- **Modelo:** o `gpt-6-luna` reproduz o histórico do pipeline de perguntas; consultar os modelos disponíveis no Codex CLI antes da primeira execução real.
- **Quotas:** não é possível inferir dos tokens a quota exata da conta ChatGPT; observar tempos, avisos e limites do serviço. As 50 histórias são indispensáveis para estimar a escala.
- **Licenças:** confirmar os direitos de adaptação e uso dos dois datasets antes de qualquer redistribuição; dados brutos e outputs ficam ignorados pelo Git.