# TinySLM-PTPT — construção integral do dataset (v1.2)

**Propósito:** preparar dados de treino de um modelo pequeno (~50 M parâmetros) com saídas em **português europeu**. Nunca se incluem histórias PT-BR cruas. A configuração contratual das fontes e metas está em [`corpus_v1.json`](corpus_v1.json).

**Estado:** ferramentas implementadas e testadas com *fixtures* locais. **Os corpora completos não foram descarregados nem transformados, o modelo de adaptação não foi executado e o dataset não está pronto para treino real.** O comando `pipeline_ptpt.py estado` mostra o que falta. Quotas são objetivos, não uma contagem de ficheiros existentes.

## Objetivos

| Componente | Fontes | Meta | Saída |
|---|---|---:|---|
| 1. Geral, PT-PT | CETEMPúblico 1.7, Bagaço2, ParlaMint-PT, ELTeC-por, Adamastor | 400 M **tokens reais** | `release/v1/train.jsonl.gz` + `validation.jsonl.gz` |
| 2. Histórias simples, PT-PT | TinyStories-pt-BR e Boakpe, **após adaptação e auditoria** | 100 000 **histórias aceites**, 25–35 M tokens estimados | `historias/aprovadas/*/historias_train.jsonl.gz` |
| 3. Compreensão | FairytaleQA translated ptPT | 232/23/23 histórias por split; 10 580 QA no total | `release/v1/qa/qa_{train,validation,test}.jsonl.gz` |

**Fases de treino separadas:** português geral → histórias adaptadas (com mistura de manutenção do geral, a planear no notebook) → QA supervisionado → especialização culinária. A estimativa global de 425–435 M tokens refere-se à *quantidade de dados*, **não** a uma dose automática nem a epochs já definidas.

## Requisitos e segurança

- Python 3.10+ e espaço em disco suficiente (múltiplos GB para as fases gerais e binários). Os programas de processamento base usam biblioteca padrão; apenas transferências HF precisam de `datasets`, o tokenizer precisa de `tokenizers`.
- **Não publicar textos originais nem binários de treino** sem auditar licenças; o código não contém textos dos datasets. A exportação para Kaggle exige confirmação explícita de destino privado.
- A classificação PT-PT do Bagaço2 é uma **heurística**; os filtros de brasileirismos também. É indispensável uma auditoria linguística manual por amostras, e proteger train/validation de textos quase iguais.
- Não há fallback que transforme automaticamente textos em PT-PT: se o serviço de adaptação falhar, o texto recebe `status=error` e **não** passa à publicação.
- O pipeline é **imutável**: não sobrescreve ficheiros de saída; versões novas usam novas pastas. A adaptação permite retomar a mesma saída sem duplicar os IDs já convertidos.

## 0. Instalar e verificar o estado

**Criar primeiro um ambiente Conda isolado** (não executar `pip install` no `(base)`: `datasets` e `tokenizers` modernos podem entrar em conflito com `transformers` antigos e `petals`). Na raiz do repositório:

```bash
conda create -n tinyslm-ptpt python=3.11 -y
conda activate tinyslm-ptpt
python -m pip install -r tools/corpus_ptpt/requirements-corpus.txt
python -m pip check
```

Depois, verificar os testes e o estado:

```bash
python -m unittest discover -s tools/corpus_ptpt -p 'test_*.py' -v
python tools/corpus_ptpt/pipeline_ptpt.py estado
```

No Windows, substituir `python3` por `python` se necessário. As **únicas dependências obrigatórias para executar os testes** são as da biblioteca padrão do Python.

## 1. Recolher e limpar o corpus PT-PT geral

Criar pastas e colocar o ficheiro disponibilizado pela Linguateca:

```bash
mkdir -p dados/corpus_ptpt/raw
# guardar neste local: dados/corpus_ptpt/raw/CETEMPublico1.7.gz
python3 tools/corpus_ptpt/build_ptpt.py cetem
```

A leitura é em streaming sobre o `.gz`, sem o extrair. Confirmar regras de utilização: [CETEMPúblico](https://www.linguateca.pt/cetempublico/index_info.html).

**Bagaço2**: `all` significa corpus completo; `sample` é apenas uma amostra de ~79 mil documentos. O limite abaixo é em **palavras** (a contagem final de tokens requer BPE).

```bash
python3 tools/corpus_ptpt/build_ptpt.py bagaco \
  --config all --ptpt-min 0.90 --edu-min 2 --palavras-alvo 120000000
```

**ELTeC-por**: implementado download autónomo apenas dos XML de nível 1, com verificação SHA-1 do Git blob e reutilização de downloads já verificados. Evita obter a árvore enorme inteira ou os níveis 0/2 duplicados.

```bash
python3 tools/corpus_ptpt/fontes_literarias.py obter-eltec
python3 tools/corpus_ptpt/fontes_literarias.py eltec \
  --input-dir dados/corpus_ptpt/raw/eltec_level1 \
  --out dados/corpus_ptpt/processed/eltec.jsonl.gz
```

**ParlaMint-PT**: obter o corpus **de Portugal**, formato XML TEI (não apenas o repositório GitHub, que contém sobretudo scripts/amostras). Consultar [CLARIN ParlaMint](https://www.clarin.eu/parlamint). Colocar as sessões `.xml` em `dados/corpus_ptpt/raw/parlamint_xml/` (ignorar `.ana.xml`, anotação) e executar:

```bash
python3 tools/corpus_ptpt/fontes_literarias.py parlamint \
  --input-dir dados/corpus_ptpt/raw/parlamint_xml \
  --out dados/corpus_ptpt/processed/parlamint.jsonl.gz
```

**Projecto Adamastor**: selecionar EPUB em domínio público, preferencialmente autores portugueses que não constem já do ELTeC; colocar em `dados/corpus_ptpt/raw/adamastor_epub/`. [Catálogo](https://projectoadamastor.org/catalogo/). O extrator respeita a ordem de leitura (`spine`) do EPUB.

```bash
python3 tools/corpus_ptpt/fontes_literarias.py adamastor \
  --input-dir dados/corpus_ptpt/raw/adamastor_epub \
  --out dados/corpus_ptpt/processed/adamastor.jsonl.gz
```

Os romances são divididos em blocos até 12 mil caracteres **com a mesma chave de obra**. Isso corrige a versão anterior, que poderia eliminar um romance completo por exceder o tamanho máximo. Ao criar validação, os blocos da mesma obra permanecem no mesmo split.

**Importante:** para a v1 completa, ter as **cinco** fontes presentes e auditadas. O alvo de 400 M tokens depende da disponibilidade real. O reequilibrador impõe **tetos de tokens por origem** (200 M Bagaço2, 150 M CETEMPúblico, 20 M ParlaMint, 30 M narrativa), preenchendo carências com documentos Bagaço2 adicionais quando existem; nunca fabrica textos para perfazer quotas. Remover textos quase duplicados e avaliar a composição antes de treinar.

## 2. Recolher e adaptar 100 000 histórias

Existem scripts de recolha reais para os campos HF correspondentes: TinyStories usa `text`/equivalente e Boakpe usa `texto`. Os downloads são feitos com `streaming=True`, para não trazer milhões de histórias à memória.

```bash
python3 tools/corpus_ptpt/historias_ptpt.py recolher --dataset tinystories \
  --max-rows 120000 --out dados/corpus_ptpt/historias/raw/tinystories.jsonl.gz
python3 tools/corpus_ptpt/historias_ptpt.py recolher --dataset historinhas \
  --max-rows 60000 --out dados/corpus_ptpt/historias/raw/historinhas.jsonl.gz
```

**120 mil + 60 mil são candidatos, não histórias aprovadas.** É provável precisar de recolher mais, após perdas por qualidade e deduplicação. Não são histórias PT-PT nesta fase.

**Conversão com um modelo externo/local:** o script aceita um endpoint **OpenAI-compatible**. Por omissão procura `http://127.0.0.1:11434/v1/chat/completions` (Ollama, se instalado e a executar). O modelo escolhido **tem de ser capaz de produzir PT-PT corretamente**. Em serviços remotos requer HTTPS e usa chave indicada pela variável de ambiente (não fica guardada nos resultados). **100 mil adaptações têm custo substancial de tempo/energia e poderão ter custos monetários.** Testar com `--limit 50` e rever a qualidade antes de escalar.

```bash
python3 tools/corpus_ptpt/historias_ptpt.py adaptar \
  --raw dados/corpus_ptpt/historias/raw/tinystories.jsonl.gz \
  --out dados/corpus_ptpt/historias/adaptados/tinystories.jsonl.gz \
  --model NOME_DO_MODELO_PTPT --limit 50
```

Para continuar a mesma saída, executar **o mesmo comando sem `--limit`**. O script reconhece IDs já processados e retoma; erros ficam registados e não são aceites. Repetir para `historinhas`, mudando `--raw` e `--out`.

**Auditar e gerar revisão humana:**

```bash
python3 tools/corpus_ptpt/historias_ptpt.py auditar \
  --adaptados dados/corpus_ptpt/historias/adaptados/tinystories.jsonl.gz \
  --out dados/corpus_ptpt/historias/auditoria/tinystories.jsonl.gz
python3 tools/corpus_ptpt/historias_ptpt.py amostrar \
  --auditados dados/corpus_ptpt/historias/auditoria/tinystories.jsonl.gz \
  --csv dados/corpus_ptpt/historias/revisao/tinystories.csv --por-lote 20
```

Abrir o CSV e **avaliar cada amostra de cada lote** (1000 histórias por lote, 20 amostras). Preencher a coluna `aprovada` com `sim` ou `não`. Uma amostra rejeitada ou por rever bloqueia o lote inteiro. Isto não constitui uma prova absoluta: convém alargar a amostragem e rever lotes com muitos avisos. Não colocar `sim` automaticamente.

```bash
python3 tools/corpus_ptpt/historias_ptpt.py publicar \
  --auditados dados/corpus_ptpt/historias/auditoria/tinystories.jsonl.gz \
  --revisao dados/corpus_ptpt/historias/revisao/tinystories.csv \
  --out-dir dados/corpus_ptpt/historias/aprovadas/tinystories --por-lote 20
```

Repetir a sequência para `historinhas`, com os caminhos correspondentes. A publicação aplica deduplicação **exata e aproximada** (trigramas + MinHash/Jaccard), e cria os splits `historias_train.jsonl.gz` e `historias_validation.jsonl.gz`.

**Juntar e deduplicar entre as duas fontes, sem aceitar PT-BR cru:**

```bash
python3 tools/corpus_ptpt/historias_ptpt.py juntar-aprovadas \
  --fontes dados/corpus_ptpt/historias/aprovadas/tinystories \
           dados/corpus_ptpt/historias/aprovadas/historinhas \
  --out-dir dados/corpus_ptpt/historias/final/v1 --meta-historias 100000
```

Só o relatório de `historias/final/v1/historias_report.json` indica quantas histórias realmente únicas foram aceites. O treino narrativo será codificado com o **mesmo tokenizer PT-PT** do corpus geral.


**Atenção:** qualquer conversão feita com LLM é uma adaptação, não uma tradução certificada. O modelo de 50 M não deve ser o tradutor de si próprio; a adaptação exige um modelo português competente ou revisão humana.

## 3. FairytaleQA — compreensão supervisionada

```bash
python3 tools/corpus_ptpt/build_ptpt.py fairytale
python3 tools/corpus_ptpt/pipeline_ptpt.py preparar-qa
```

O script extrai sem duplicar os contextos por pergunta e cria três conjuntos de mensagens (system/user/assistant) com os splits originais `train/validation/test`. **Só `train` alimenta treino supervisionado**; o conjunto de teste nunca entra no pré-treino nem no SFT.

## 4. Finalizar, tokenizar e auditar o corpus geral

Depois de existirem as cinco fontes processadas:

```bash
python3 tools/corpus_ptpt/pipeline_ptpt.py estado
python3 tools/corpus_ptpt/pipeline_ptpt.py finalizar-geral
```

`finalizar-geral` recusa criar o release completo se faltar alguma fonte. Para um **ensaio não definitivo**, pode usar `--permitir-parcial` com uma pasta de release diferente, por exemplo `--release dados/corpus_ptpt/release/ensaio`.

Escreve:

```
dados/corpus_ptpt/release/v1/
  train.jsonl.gz
  validation.jsonl.gz
  dataset_report.json
  equilibrado/train.jsonl.gz
  equilibrado/validation.jsonl.gz
  equilibrado/quota_report.json
  tokenizer/tokenizer.json
  tokenizer/tokenizer_config_ptpt.json
  bin/train.bin
  bin/validation.bin
  bin/pack_report.json
  auditoria_report.json
  qa/qa_train.jsonl.gz
  qa/qa_validation.jsonl.gz
  qa/qa_test.jsonl.gz
```

**Nota:** o tokenizer BPE de 8192 tokens é treinado **só com os textos gerais**. É preciso verificar a cobertura linguística sobre histórias adaptadas, e eventualmente refazer o tokenizer antes de avançar para o treino. O binário dos dados gerais será little-endian `uint16`.

A tokenização do `train` serve de base ao reequilíbrio: o script `equilibrar_corpus.py` calcula primeiro os tokens reais, corta por quotas de fonte e produz os ficheiros `equilibrado/*`; **os binários são preparados a partir desses ficheiros equilibrados, e não do merge bruto**. Os ficheiros `dataset_report.json`, `equilibrado/quota_report.json` e `bin/pack_report.json` reportam contagens medidas, não projeções. O `auditoria_report.json` assinala falhas estruturais e se a quota dos 400 M tokens foi atingida. **Uma auditoria estrutural com sucesso não dispensa controlo qualitativo nem auditoria de licenças.**

## 5. Exportar ficheiros para Kaggle privado

```bash
python3 tools/corpus_ptpt/finalizar_dataset.py kaggle \
  --release dados/corpus_ptpt/release/v1 \
  --out dados/corpus_ptpt/release/tinyslm_ptpt_geral_kaggle.zip \
  --include-qa --destino-privado-confirmado
```

Só inclui os binários, tokenizer e QA de treino/validação; **não inclui** os ficheiros brutos nem o teste de QA. A flag de destino privado não substitui uma avaliação jurídica das licenças de cada fonte.

**Ainda falta uma fase externa a estes scripts:** adaptar o notebook de treino no Kaggle a `train.bin`/`validation.bin`, e integrar a fase de histórias para treinar os pesos de raiz. Os ficheiros são preparados para esse treino, mas os scripts do corpus **não iniciam treino**.

## Manutenção

- Antes de cada execução, correr `python3 tools/corpus_ptpt/pipeline_ptpt.py estado`.
- Testes: `python3 -m unittest discover -s tools/corpus_ptpt -p 'test_*.py' -v`.
- Histórico de progresso: [`TAREFAS.md`](TAREFAS.md).
- Não alterar as três componentes acordadas sem atualizar o manifesto e os testes.