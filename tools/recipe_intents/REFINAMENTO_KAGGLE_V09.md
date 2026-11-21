# Refinamento TinySLM C2 v09 — guia rápido Kaggle

## 1. Preparação

No Kaggle, abrir **Add Input** e garantir três datasets privados:

1. `epoca3`: com uma pasta `epoch_3` e `model.safetensors`, `config.json`,
   `tokenizer.json`, `tokenizer_config.json` (pesos anteriores do TinySLM).
2. Dataset novo contendo **`TinySLM_C2_intents_sft_v01.zip`**. Fazer download
   do ficheiro do diretório `data/intent_teacher/` no GitHub e carregá-lo como
   input Kaggle (ou carregar os ficheiros extraídos do ZIP).
3. `TinySLM Culinary Conversations v04`: com `train.jsonl`, `validation.jsonl`,
   `dataset_report.json`, para preservar a capacidade de responder sobre receitas.

Abrir `notebooks/TinySLM_C2_v09_refinamento_intencoes.ipynb` no Kaggle e ativar
**GPU T4** ou equivalente. Em **Save Version**, selecionar **Save & Run All**.

## 2. O que o notebook faz

- Carrega `epoch_3`, sem iniciar um modelo novo ou alterar tokenizer.
- Confirma 17.783 linhas de treino, 1.040 de validação e 1.027 de teste.
- Constrói prompts de **classificação sem contexto da receita**, com resposta
  `{"intent":"quantity","operation":"get"}`.
- Mistura uma pequena amostra C1–C7 das conversas v04, excluindo quaisquer
  grupos de receitas reservados à validação/teste de intenções.
- Regista o comportamento **antes** do refinamento.
- Executa inicialmente **2 épocas**, guarda checkpoints por época e mede a
  concordância face aos rótulos teacher, bem como a perda nas receitas antigas.
- Exporta `TinySLM_C2_v09_refinamento_resultados.zip` para o **Output**.

## 3. Interpretação

Os 20.000 rótulos foram gerados automaticamente e **não são gold labels**.
Foram excluídos 200 casos com pares intenção/operação fora da taxonomia. O
conjunto de teste continua a ser provisório; sem revisão independente, a
concordância com o professor não é uma medição certificada de precisão.

Antes de declarar o modelo pronto, rever manualmente uma amostra (especialmente
`unknown`, `ingredients/check`, `quantity/get`, `steps/explain` e multi-pedido),
avaliar perguntas novas e verificar regressões nas conversas culinárias v04.
O notebook é **código preparado, ainda não executado na GPU do Kaggle**.
