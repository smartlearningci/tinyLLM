# Modelos e resultados

## Base inglesa

Copia a pasta completa `473_B1` para `modelos/base_473M/`. A partir da raiz do repositório, usa a localização real da pasta de origem:

```bash
cp -a "/caminho/para/473_B1" modelos/base_473M
```

Substitui `/caminho/para/473_B1` pelo caminho indicado no teu gestor de ficheiros. Executa apenas uma vez e confirma que `modelos/base_473M` ainda não existe, para não criar uma pasta aninhada.

Conteúdo esperado: model.safetensors, config.json, generation_config.json, tokenizer.json, tokenizer_config.json, metrics.json, training_state.pt. O conteúdo do estado de treino não foi inspecionado; não assumimos retoma exata só pela sua presença.

Cópia Kaggle: consulta o dataset `tinyslm-chat-mvp-v01` na tua conta Kaggle (secção Datasets).
O tokenizer base desta pasta não deve ser confundido com o tokenizer de chat usado no SFT.

## Cada treino culinário

Cria uma pasta por experiência: modelos/culinario_v03/, modelos/culinario_v04/, etc. Guarda os pesos e resultados descarregados do Kaggle. O painel procura metrics.json e run_config.json dentro destas pastas. Não carrega os pesos em memória.

Anota num pequeno README de cada experiência: objetivo, versão do código, dataset Kaggle e versão, checkpoint base, melhor checkpoint e observações sobre respostas.

## GitHub

Os pesos, dados e resultados locais são excluídos do Git. Permanecem no PC e no Kaggle. Uma publicação futura de pesos numa Release será uma operação separada. Conserva uma cópia de segurança.
