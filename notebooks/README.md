# Notebooks

## Qual usar

- 00_preparacao_base_60M.ipynb: experiência histórica com seis arquiteturas e treino inicial até 60M tokens. Não é necessário repetir para treinar receitas.
- 01_treino_base_ingles.ipynb: continua F_h512_L12_60M.zip até ~473M tokens TinyStories. Não começa com pesos aleatórios. RUN_TRAINING=False no original.
- 02_treino_receitas.ipynb: SFT culinário a partir de 473_B1, com tokenizer de chat e dataset exportado.

Os dois primeiros mantêm o código original. No culinário foram adaptados os nomes dos inputs para train.jsonl, validation.jsonl, dataset_report.json e acrescentado RUN_NAME. Mantêm-se seed 42, contexto 512, 3 epochs e LR 5e-5. Só as respostas do assistente contribuem para a loss. Exemplos longos são excluídos e registados; não são truncados.

O notebook inglês grava final_473M; a relação exata com a pasta posteriormente chamada 473_B1 ainda deve ser confirmada pelos metadados. Não afirmar equivalência apenas pelo nome.

## Próximo treino

Segue [NOVO_TREINO.md](NOVO_TREINO.md). Não é necessário voltar a executar o treino inglês.

Notebook histórico no Kaggle: https://www.kaggle.com/code/eduardocatarino/tinyslm-culinary-poc
Dataset dos pesos: https://www.kaggle.com/datasets/eduardocatarino/tinyslm-chat-mvp-v01
