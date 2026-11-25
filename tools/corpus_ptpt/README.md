# TinySLM-PTPT — preparar o corpus geral e a compreensão de histórias

Objetivo: construir um dataset de pré-treino **português de Portugal** sem misturar o corpus culinário nesta fase. Não descarrega nem publica automaticamente corpora no GitHub; os dados são gerados em `dados/corpus_ptpt/`, que está ignorado pelo Git.

## Fontes e limites

- **CETEMPúblico 1.7:** texto jornalístico português. Colocar manualmente `CETEMPublico1.7.gz` em `dados/corpus_ptpt/raw/`; o leitor processa o `.gz` sem o descomprimir para disco. Formato original SGML; não usar os corpora anotados de vários GB. Condições da Linguateca/PÚBLICO aplicam-se.
- **Bagaço2:** `duarteocarmo/fineweb2-bagaco2` no Hugging Face. **ATENÇÃO:** a configuração HF predefinida é `sample`, de 79 mil linhas; para a recolha verdadeira é obrigatório usar a configuração **`all`**. O programa força `all` por omissão e utiliza `streaming=True`. Aplica `ptpt_score >= 0.90`, `educational_score >= 2` por omissão. São filtros heurísticos; a variante não é garantida a 100%.
- **ParlaMint-PT**, **ELTeC-por** e **Projecto Adamastor**: depois de converter/obter os textos em ficheiros `.txt` UTF-8 devidamente autorizados, importá-los através de `textos`. A conversão de XML/EPUB e a seleção de obras adequadas ainda precisam de ser efetuadas; o script **não** as faz automaticamente.
- **FairytaleQA PT-PT:** `benjleite/FairytaleQA-translated-ptPT`. São 10.580 pares de perguntas/respostas baseados em **278 histórias**, não 10.580 histórias. A coluna `story_section` contém *excertos*, não necessariamente o conto completo. Guarda-se cada excerto uma única vez por split e os QA em ficheiros separados. **Apenas excertos de `train` entram no pré-treino**; os de `validation` e `test` são reservados para avaliação.

O dataset inclui texto português escrito antes do Acordo Ortográfico e linguagem literária antiga. Não se reescreve automaticamente a ortografia. Filtrar posteriormente por qualidade real e diversidade antes de considerar a coleção definitiva. Faz-se deduplicação exata de documentos (não uma deduplicação semântica de paráfrases) e divisão estável por grupo. O `educational_score` do Bagaço2 é um classificador imperfeito.

## Instalação e execução

Na raiz do repositório:

```bash
python3 -m pip install -U datasets tokenizers
mkdir -p dados/corpus_ptpt/raw
# colocar aqui o CETEMPublico1.7.gz previamente descarregado
```

1. **Converter todo o CETEMPúblico** já descarregado:

```bash
python3 tools/corpus_ptpt/build_ptpt.py cetem
```

2. **Obter o Bagaço2 PT-PT em streaming**, sem descarregar previamente 37 GB. A meta é um número de **palavras** e não tokens; ajustar posteriormente ao tokenizer real. Poderá demorar várias horas dependendo da ligação.

```bash
python3 tools/corpus_ptpt/build_ptpt.py bagaco --config all --palavras-alvo 120000000
```

3. **Obter o FairytaleQA (todos os splits; avaliação preservada):**

```bash
python3 tools/corpus_ptpt/build_ptpt.py fairytale
```

4. **Fontes adicionais em texto (depois de as obter/converter), uma por origem:**

```bash
python3 tools/corpus_ptpt/build_ptpt.py textos \
  --input-dir dados/corpus_ptpt/raw/parlamint_textos \
  --source parlamint_pt \
  --out dados/corpus_ptpt/processed/parlamint.jsonl.gz
```

Repetir com as pastas e nomes correspondentes para `eltec_por` e `adamastor`. Não misturar romances de origem desconhecida ou contos duplicados.

5. **Juntar os textos para pré-treino**, incluindo exclusivamente os contextos `train` do FairytaleQA. Para já, com as três fontes cujo acesso foi automatizado:

```bash
python3 tools/corpus_ptpt/build_ptpt.py juntar \
  --out-dir dados/corpus_ptpt/release/v1 \
  --inputs \
  dados/corpus_ptpt/processed/cetem.jsonl.gz \
  dados/corpus_ptpt/processed/bagaco.jsonl.gz \
  dados/corpus_ptpt/processed/fairytale_contextos_train.jsonl.gz
```

Adicionar `dados/corpus_ptpt/processed/parlamint.jsonl.gz` e os restantes ficheiros `*.jsonl.gz` à lista `--inputs` **se e só se** já estiverem prontos. O script escreve:

- `train.jsonl.gz` — textos para treino;
- `validation.jsonl.gz` — validação do modelo base, por grupos;
- `dataset_report.json` — contagem de documentos e palavras por fonte;
- `processed/fairytale_qa_train.jsonl.gz`, `...validation...`, `...test...` — tarefas de compreensão a manter separadas.

Nenhum ficheiro existente é substituído automaticamente. Em caso de nova versão, usar `release/v2`.

6. **Treinar tokenizer BPE de 8.192 tokens só com o treino:**

```bash
python3 tools/corpus_ptpt/preparar_treino.py tokenizer
```

7. **Codificar para binário little-endian uint16, para o treino no Kaggle:**

```bash
python3 tools/corpus_ptpt/preparar_treino.py pack
```

Geram-se `release/v1/bin/train.bin`, `validation.bin`, `pack_report.json` com a contagem **real de tokens**. Só depois aferir o objetivo de aproximadamente 400 milhões de tokens, definir o treino e adaptar `notebooks/01_treino_base_ingles.ipynb` ao tokenizer/PT-PT/ficheiros binários. O treino dos pesos **não é iniciado por estes scripts**.

## Verificações e reprodutibilidade

```bash
python3 -m unittest discover -s tools/corpus_ptpt -p 'test_*.py' -v
```

Os testes são locais e usam exemplos artificiais; **não equivalem à validação do download completo nem à auditoria linguística das centenas de milhões de tokens**. Antes de executar treino longo, confirmar o tamanho final, distribuição entre fontes, contagens de tokens, qualidade PT-PT e eventuais textos quase duplicados. Rever os termos de reutilização de cada fonte, sobretudo antes de publicar datasets ou pesos.

### Princípios

1. **Modelo PT-PT de raiz**, novo tokenizer e pesos; não usar tokenizer inglês antigo.
2. **Pré-treino geral**, depois treino narrativo/conversacional e só depois especialização em receitas.
3. **FairytaleQA validation/test reservados**; nunca contaminar o pré-treino com esses excertos.
4. **Sem histórias fictícias em massa** para atingir arbitrariamente uma meta.
5. **Sem corpus no repositório de código**, apenas scripts, documentação e testes.