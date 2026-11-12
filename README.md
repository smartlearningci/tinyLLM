# tinyLLM

Modelo pequeno de língua inglesa, adaptado a receitas. Geração de conversas por chat ou Codex CLI; treino no Kaggle. Projeto autónomo: não usa caminhos das pastas antigas.

## Instalar no PC (Linux)

```bash
cd ~/Documentos/Alunos/SmartLearning/tiny_v2
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

- [Dados e estados](dados/README.md)
- [Gerar aqui no chat](dados/GERAR_CHAT.md)
- [Gerar automaticamente por CLI](dados/GERAR_CLI.md)
- [Notebooks](notebooks/README.md)
- [Novo treino no Kaggle](notebooks/NOVO_TREINO.md)
- [Pesos e resultados](modelos/README.md)

Estes mesmos guias aparecem no painel em Instruções. Os ficheiros Markdown são a fonte única.

Para atualizar o código: `git pull --ff-only`. Dados e modelos estão excluídos do Git. Faz cópias de segurança locais separadas.

Testes: `python -m unittest -v`. Não consomem quota nem treinam modelos.
