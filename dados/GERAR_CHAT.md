# Gerar conversas no chat

Executar comandos na raiz de tinyLLM, depois de `source .venv/bin/activate`.

## 1. Preparar pedidos

Espera pelo fim do lote CLI antes de reservar. Usa uma pasta nova por ronda:

```bash
python distill.py prompts --provider chatgpt --limit 10 --batch-size 2 --out dados/prompts/ronda_001
mkdir -p dados/respostas/ronda_001
```

Resultado: até cinco ficheiros .txt, cada um com dois pedidos e até 12 conversas. Os pedidos ficam manual e deixam de ser selecionados pela CLI. O limite é número de pedidos, não de receitas.

## 2. Enviar aqui

Anexa um ou dois .txt e pede: «Executa os pedidos destes ficheiros e devolve um ficheiro JSON completo para importar, preservando job_id, slots e citações.»

Não alteres os IDs. Se a resposta estiver cortada, pede o ficheiro completo antes de importar.

## 3. Arquivar o resultado

Descarrega o JSON para dados/respostas/ronda_001/. Usa nomes diferentes: resposta_001.json, resposta_002.json. Se descarregar para Downloads, move o ficheiro pelo gestor de ficheiros.

## 4. Importar

```bash
python distill.py import dados/respostas/ronda_001 --provider chatgpt --teacher chatgpt-manual
python distill.py status
```

O programa arquiva também a resposta em raw/, valida cada pedido e guarda as conversas. Concluídos são ignorados numa reimportação. Num lote parcialmente inválido, os válidos ficam guardados; corrige apenas os inválidos e reimporta.

## 5. Visualizar

```bash
python monitor.py --port 8766
```

Abre http://127.0.0.1:8766 → Respostas. Filtra por persona/capacidade/estado e abre a conversa. Em Pedidos podes consultar o prompt completo.

## Próxima ronda ou recuperação

Troca ronda_001 por ronda_002. Para recuperar prompts reservados que não guardaste:

```bash
python distill.py prompts --status manual --provider chatgpt --limit 10 --batch-size 2 --out dados/prompts/recuperados
```

Para devolver uma reserva específica à CLI: `python distill.py retry --job ID_DO_PEDIDO`. Não o faças se já estiveres a gerar a resposta desse pedido no chat.
