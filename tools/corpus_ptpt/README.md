# TinySLM-PTPT — corpus geral, histórias simples e compreensão

Objetivo: construir dois conjuntos de pré-treino **em português de Portugal** — geral e histórias simples — e um terceiro de compreensão supervisionada, sem misturar o corpus culinário nesta fase. Não descarrega nem publica automaticamente corpora no GitHub; os dados são gerados em `dados/corpus_ptpt/`, que está ignorado pelo Git.


## Composição fechada — PT-PT v1.1 (três componentes)

A definição oficial está em [`corpus_v1.json`](corpus_v1.json). **São metas e não dados já recolhidos**, e os scripts atuais ainda não aplicam automaticamente todas as quotas.

### 1 — Corpus geral: 400 milhões de tokens PT-PT

| Fonte | Quota indicativa | Estado da recolha |
|---|---:|---|
| Bagaço2 PT-PT | 200 M tokens | streaming implementado |
| CETEMPúblico 1.7 | 150 M tokens | leitura `.gz` implementada |
| ParlaMint-PT | até 20 M tokens | conversão de origem pendente |
| ELTeC-por + Adamastor | até 30 M tokens no conjunto | extração/seleção pendentes |

### 2 — Histórias simples adaptadas: 100.000 histórias PT-PT

Usar [`DominuZ/TinyStories-pt-BR`](https://huggingface.co/datasets/DominuZ/TinyStories-pt-BR) como fonte principal e [`Boakpe/historinhas`](https://huggingface.co/datasets/Boakpe/historinhas) como complemento. **Não usar texto PT-BR diretamente**. Adaptar à linguagem natural de Portugal e validar, preservar o original e eliminar repetições e histórias quase iguais. Meta de 100.000 histórias **aceites**; previsão de 25–35 M tokens, a medir depois da tokenização.

Este corpus de histórias **ainda não está construído**. O pipeline de conversão e auditoria ainda tem de ser desenvolvido. Não se trata de tradução palavra a palavra ou da criação massiva de histórias novas sem controlo de qualidade. Treinar como fase narrativa posterior ao corpus geral.

### 3 — Compreensão e conversação: FairytaleQA PT-PT

O dataset [`benjleite/FairytaleQA-translated-ptPT`](https://huggingface.co/datasets/benjleite/FairytaleQA-translated-ptPT) fica fora do corpus de pré-treino geral e das histórias adaptadas. Guardar os pares de perguntas/respostas para uma fase supervisionada; manter os splits originais e reservar validação/teste para avaliação. Evitar que as mesmas histórias/variantes apareçam no pré-treino.

**Total de pré-treino previsto: aproximadamente 425–435 milhões de tokens**, mais os exemplos supervisionados. **O treino e a recolha integral ainda não ocorreram.** O código atual em `build_ptpt.py` suporta o corpus geral parcialmente e a extração do FairytaleQA, mas **não gera nem valida as 100.000 histórias adaptadas**.

## Fontes e limites

- **CETEMPúblico 1.7:** texto jornalístico português. Colocar manualmente `CETEMPublico1.7.gz` em `dados/corpus_ptpt/raw/`; o leitor processa o `.gz` sem o descomprimir para disco. Formato original SGML; não usar os corpora anotados de vários GB. Condições da Linguateca/PÚBLICO aplicam-se.
- **Bagaço2:** `duarteocarmo/fineweb2-bagaco2` no Hugging Face. **ATENÇÃO:** a configuração HF predefinida é `sample`, de 79 mil linhas; para a recolha verdadeira é obrigatório usar a configuração **`all`**. O programa força `all` por omissão e utiliza `streaming=True`. Aplica `ptpt_score >= 0.90`, `educational_score >= 2` por omissão. São filtros heurísticos; a variante não é garantida a 100%.
- **ParlaMint-PT**, **ELTeC-por** e **Projecto Adamastor**: depois de converter/obter os textos em ficheiros `.txt` UTF-8 devidamente autorizados, importá-los através de `textos`. A conversão de XML/EPUB e a seleção de obras adequadas ainda precisam de ser efetuadas; o script **não** as faz automaticamente.
- **Histórias simples PT-PT:** ainda não automatizadas; os textos de DominuZ e Boakpe precisam de adaptação, validação e deduplicação antes de poderem ser incluídos. A saída futura deverá estar separada do corpus geral.
- **FairytaleQA PT-PT:** `benjleite/FairytaleQA-translated-ptPT`. São 10.580 pares de perguntas/respostas baseados em **278 histórias**, não 10.580 histórias. A coluna `story_section` contém *excertos*, não necessariamente o conto completo. Os contextos e os QA são guardados por split, **mas não entram no pré-treino geral v1**. Para compreensão, usar apenas o split `train` no treino; `validation` e `test` ficam reservados para avaliação.

O dataset inclui texto português escrito antes do Acordo Ortográfico e linguagem literária antiga. Não se reescreve automaticamente a ortografia. Filtrar posteriormente por qualidade real e diversidade antes de considerar a coleção definitiva. Faz-se deduplicação exata de documentos (não uma deduplicação semântica de paráfrases) e divisão estável por grupo. O `educational_score` do Bagaço2 é um classificador imperfeito. As quotas finais têm de ser medidas com o tokenizer e verificadas antes do treino.

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

5. **Juntar os textos para pré-treino**, sem incluir o FairytaleQA. Para já, com as duas fontes gerais cujo acesso foi automatizado:

```bash
python3 tools/corpus_ptpt/build_ptpt.py juntar \
  --out-dir dados/corpus_ptpt/release/v1 \
  --inputs \
  dados/corpus_ptpt/processed/cetem.jsonl.gz \
  dados/corpus_ptpt/processed/bagaco.jsonl.gz
```

Adicionar `dados/corpus_ptpt/processed/parlamint.jsonl.gz`, `eltec.jsonl.gz` e `adamastor.jsonl.gz` à lista `--inputs` **se e só se** já estiverem prontos, sem ultrapassar as quotas estabelecidas no manifesto após tokenização. **Não adicionar `fairytale_contextos_train.jsonl.gz` no corpus oficial v1.** O script escreve:

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
3. **FairytaleQA inteiramente fora do pré-treino geral v1**; reservar os splits de validação e teste para avaliação de compreensão narrativa.
4. **Com histórias PT-BR adaptadas e validadas para PT-PT** como fase narrativa, sem gerar histórias novas em massa para cumprir quotas.
5. **Sem corpus no repositório de código**, apenas scripts, documentação e testes.