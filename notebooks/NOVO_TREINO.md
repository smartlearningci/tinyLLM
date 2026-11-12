# Novo treino no Kaggle

## 1. Conservar a validação anterior

Recupera validation_v01.jsonl do pacote culinário v02 já usado e coloca-o em dados/validation_v01.jsonl. Pode ser descarregado dos inputs do notebook antigo. Não voltes a sortear a validação entre experiências.

## 2. Preparar a nova versão

Na raiz do projeto, depois de terminar a geração:

```bash
python preparar.py treino --validation dados/validation_v01.jsonl --nome culinario_v03
```

São criados em dados/exports/culinario_v03/:
- train.jsonl: conversas auto_valid ou accepted, excluindo demonstrações e receitas relacionadas com a validação.
- validation.jsonl: cópia exata da validação anterior.
- dataset_report.json: contagens e hashes para verificar os inputs.

O programa recusa sobrescrever versões. Novas conversas das receitas de validação ficam na base de dados, fora do treino. O filtro usa ID, grupo de origem e texto normalizado, mas não deteta todas as paráfrases semanticamente semelhantes.

## 3. Atualizar o dataset Kaggle

No Kaggle, abre o dataset das conversas e cria uma nova versão com os três ficheiros acima, ou cria um dataset privado novo. Dá-lhe uma descrição com o nome culinario_v03 e as contagens do relatório. Confirma a lista de ficheiros antes de guardar. Não é o dataset dos pesos: mantém os dois separados.

## 4. Atualizar o notebook

Cria uma cópia do notebook culinário no Kaggle e importa o ficheiro notebooks/02_treino_receitas.ipynb do repositório (opção de importação/upload de notebook). Conserva a execução anterior para comparação.

Nos inputs do notebook adiciona:
1. O dataset dos pesos tinyslm-chat-mvp-v01.
2. O tokenizer de chat tinyslm-tokenizer-ingles-bpe8k-v02-chat, se não estiver já incluído no dataset anterior.
3. A nova versão do dataset das conversas, contendo os três ficheiros.

Confirma na barra lateral a versão do dataset selecionada; atualizar o dataset não garante que um notebook já aberto mudou de versão. Remove a ligação à versão antiga das conversas para evitar descoberta ambígua.

## 5. Configurar caminhos e GPU

Ativa uma GPU nas definições da sessão. Na célula de configuração:
- RUN_NAME = "culinario_v03" (novo nome em cada execução).
- BASE_OVERRIDE: pasta que contém config.json e model.safetensors de 473_B1.
- TOKENIZER_OVERRIDE: pasta que contém o tokenizer de CHAT.
- DATA_OVERRIDE: pasta que contém dataset_report.json.

Podes deixar os overrides vazios se a descoberta for única. Em caso de erro, copia o caminho exato mostrado no explorador de inputs Kaggle; não adivinhes o caminho.

Não substituas automaticamente o tokenizer de chat pelo tokenizer base. Para comparar a quantidade de dados, recomeça dos mesmos pesos 473_B1 e mantém os parâmetros; não continues do modelo culinário anterior.

## 6. Executar e verificar

Executa as células por ordem. Antes do treino confirma os caminhos e contagens impressos. O notebook verifica hashes e separação por ID de receita. Consulta a percentagem de exemplos que cabem nos 512 tokens. Uma contagem baixa significa que o treino usa apenas parte do dataset.

No final compara validation_loss e os exemplos de generations.json. Menor loss não garante respostas factualmente corretas. Os checkpoints não guardam optimizer/RNG para retoma exata deste SFT.

## 7. Guardar a execução

Guarda uma versão executada do notebook no Kaggle e descarrega a pasta de resultados em /kaggle/working/culinario_v03 ou o ZIP que o notebook produzir. Guarda localmente em modelos/culinario_v03/:
- checkpoint escolhido e tokenizer;
- metrics.json e generations.json;
- run_config.json;
- length_audit_train.json e length_audit_validation.json;
- cópia de dataset_report.json.

Não confundas o ZIP apenas de métricas com pesos completos: confirma que o checkpoint contém model.safetensors (ou o formato efetivamente gravado). O painel Projeto e treinos mostra os resultados locais encontrados em modelos/.
