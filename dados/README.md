# Dados e estado

## O que fica aqui

- queue.sqlite: receitas, pedidos, conversas, estados e proveniência. É o ficheiro principal.
- receitas.jsonl: receitas de origem copiadas na migração.
- raw/: respostas originais e diagnóstico; gerido pelo programa.
- prompts/: lotes reservados para o chat.
- respostas/: JSON que descarregas do chat.
- exports/: datasets e relatórios.
- arquivo_antigo/: pedidos/respostas antigos copiados, que podem ainda não estar importados.

A fila recebida em 12/11/2026 tinha 5108 receitas, 1000 com pedidos planeados, 275 com resultados, 1352 pedidos concluídos e 8112 conversas. É uma fotografia histórica, não o estado atual.

## Consultar

Na raiz do projeto, com o ambiente ativo:

```bash
python distill.py status
python monitor.py --port 8766
```

O painel mostra receita e conversa lado a lado, persona, capacidades, evidências e prompt do pedido. Em Respostas abre uma conversa para aceitar, rejeitar ou marcar para rever, com nota. A revisão aguarda o fim de um lote CLI; a leitura funciona durante a geração.

Estados de pedido: pending (por executar), manual (reservado para chat), running (CLI em execução), done (concluído), error (falhou).
Estados de conversa: auto_valid (formato/citações validados), accepted (revisto e aceite), needs_review (rever), rejected (rejeitado). Validação automática não garante qualidade factual. O export normal inclui auto_valid e accepted; os restantes são excluídos.

## Planear mais receitas

```bash
python distill.py plan --limit 5000
```

Seleciona até 5000 receitas existentes, não adiciona 5000 a cada execução. Já planeadas são ignoradas. Cada receita tem até cinco pedidos, um por persona; cada pedido pede seis exemplos. Receitas demasiado longas são indicadas e ignoradas, não truncadas.

## Importar uma reserva antiga

```bash
python distill.py import dados/arquivo_antigo/respostas_copilot --provider copilot --teacher copilot-chat
```

Usa apenas se essa pasta existir. Isto preserva a origem histórica, mesmo que agora só uses chat e CLI.

## Segurança dos dados

Não apagues queue.sqlite para resolver erros. Não faças duas gerações simultâneas. Para backup simples, termina o gerador e o monitor e copia toda esta pasta. Os dados não são enviados para o GitHub por git add normal.
