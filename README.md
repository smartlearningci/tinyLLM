# tinyLLM

Modelo pequeno de língua inglesa, adaptado a receitas. Geração de conversas por chat ou Codex CLI; treino no Kaggle. Projeto autónomo: não usa caminhos das pastas antigas.

## Instalar no PC (Linux)

```bash
cd ~
git clone https://github.com/smartlearningci/tinyLLM.git
cd tinyLLM
python3 -m venv .venv
source .venv/bin/activate
```

O programa local usa só a biblioteca padrão do Python 3.10+. Para geração automática é necessária a tua instalação autenticada do Codex CLI. Não é necessário para pedidos ao chat.

## Trazer os dados existentes — uma vez

Deixa terminar a geração antiga. Depois:

```bash
python preparar.py migrar ../tinyslm_distill_v01
python distill.py status
python monitor.py --port 8766
```

Abre http://127.0.0.1:8766. A migração copia a fila, receitas, logs e pastas de pedidos/respostas. Não substitui uma fila já existente. Mantém a origem como backup. Os pesos são copiados separadamente: [modelos](modelos/README.md).

## Onde encontrar ajuda

**[Começar aqui — Fluxo completo de trabalho](docs/FLUXO_COMPLETO.md)**: guia central com os comandos pela ordem correta, objetivo das 5 108 receitas, planeamento, geração, recuperação, auditoria e próximo treino.

**[TinySLM MVP C1/C2 — histórico, requisitos e resultados R1/R2](docs/tinyslm_mvp/00_HISTORICO_E_DECISOES.md)**: nova orientação de 22/11/2026. Normalização e auditoria antes de treinar chamadas de ferramentas. Consultar também [o roteiro](docs/tinyslm_mvp/01_REQUISITOS_E_ROTEIRO.md) e [os resultados das etapas 1–2](docs/tinyslm_mvp/02_RESULTADOS_ETAPAS_1_2.md) e [a preparação C1/C2 — etapa 3](docs/tinyslm_mvp/03_ETAPA_3_C1_C2.md) e [a implementação inicial RECIPE_SEARCH — etapa 4](docs/tinyslm_mvp/04_RECIPE_SEARCH_IMPLEMENTACAO.md) e [a avaliação/melhoria V2 — etapa 5](docs/tinyslm_mvp/05_ETAPA_5_RECIPE_SEARCH_V2.md).

**[Nova arquitetura TinySLM (23/11/2026): RECIPE_CONTEXT e treino de chamadas à ferramenta](docs/tinyslm_mvp/06_NOVA_ARQUITETURA_RECIPE_CONTEXT.md)** — substitui a antiga estratégia RECIPE_SEARCH de recuperação semântica.

- [Dados e estados](dados/README.md)
- [Gerar aqui no chat](dados/GERAR_CHAT.md)
- [Gerar automaticamente por CLI](dados/GERAR_CLI.md)
- [Notebooks](notebooks/README.md)
- [Novo treino no Kaggle](notebooks/NOVO_TREINO.md)
- [Pesos e resultados](modelos/README.md)

Estes mesmos guias aparecem no painel em Instruções. Os ficheiros Markdown são a fonte única.

Para atualizar o código: `git pull --ff-only`. Dados e modelos estão excluídos do Git. Faz cópias de segurança locais separadas.

Testes: `python -m unittest -v`. Não consomem quota nem treinam modelos.

## Geração económica via Codex CLI

Para reduzir instruções repetidas, há um comando independente que gera em lotes,
mede tokens quando o Codex os reporta e não repete automaticamente falhas:

```bash
python economico.py --model gpt-6-luna --reasoning-effort low --limit 200 --batch-size 2 --max-consecutive-failures 3
```

Por omissão, o modo económico usa 20 pedidos por execução e lotes de 2. `--limit` permite até 200 pedidos por execução, respeitando a paragem preventiva após falhas consecutivas. Consulta [o guia de geração económica](docs/GERACAO_ECONOMICA.md) para erros, tokens e recuperação. Este modo não modifica a geração via chat.

## Base culinária em português (PT + BR)

Preparação de receitas, técnicas e alternativas para o TinySLM, com consulta por navegador local. O código usa apenas Python padrão e não substitui os dados anteriores.

Guia: [**Criar e consultar a base portuguesa**](docs/tinyslm_pt/README.md).

## Corpus base exclusivamente PT-PT

O pipeline de construção do dataset para o novo pré-treino em português de Portugal está em [tools/corpus_ptpt/README.md](tools/corpus_ptpt/README.md). O corpus é gerado localmente e não é publicado no GitHub.
