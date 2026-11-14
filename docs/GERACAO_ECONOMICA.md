# Geração económica com Codex CLI

O comando novo `economico.py` não altera `distill.py run`, nem substitui a base SQLite, nem executa pedidos em estado `manual`, `done` ou `error`.

## Primeiro ensaio (sem gastar quota)

```bash
git pull --ff-only
source .venv/bin/activate
python -m unittest -v
codex login status
```

## Ensaio real e configuração por omissão

Primeiro testa um único lote, confirmando a aceitação do nome do modelo no Codex instalado:

```bash
python economico.py --limit 4 --batch-size 4 --model gpt-6-luna --reasoning-effort low
```

Depois, o comando `python economico.py` utiliza por omissão o modelo `gpt-6-luna`, raciocínio `low`, por omissão 20 pedidos e 2 por lote. Pode pedir de 1 a 200 pedidos por execução com `--limit`, mantendo 2 por lote. Para alterar o raciocínio, usa `--reasoning-effort` (low, medium, high ou xhigh). Não arranca automaticamente um segundo bloco de 20. Para personalizar o ensaio, usa `--limit` (1 a 20) e `--batch-size` (1 a 4).

O modelo deve estar disponível no Codex CLI autenticado. Se não for reconhecido, a execução pára e não troca de modelo silenciosamente. O agrupamento pode economizar contexto repetido, mas não garante poupança de plafond.

## Tokens e arquivos

Em `dados/raw/`, o modo guarda por lote:

- `eco-*.manifest.json`: IDs, tentativas e modelo;
- `eco-*.events.jsonl`: eventos do Codex, incluindo métricas quando disponíveis;
- `eco-*.stderr.txt`: diagnósticos;
- `eco-*.response.json`: resposta bruta antes de guardar conversas;
- `eco-*.summary.json`: duração, tokens reportados e número de conversas gravadas.

Os tokens registados correspondem à chamada completa, não a cada pedido. Se o serviço não devolver contagens, o resumo não permite estimar o consumo real do plafond.

## Falhas e retoma conservadora

Cada pedido é validado separadamente: respostas válidas são guardadas mesmo que um dos quatro pedidos seja inválido **ou tenha sido omitido** pelo Codex. O pedido inválido ou omitido passa a `error` e a geração pára para revisão, sem repetir automaticamente a chamada. O resumo do lote fica com `status: partial` e `failed_jobs` para permitir identificar o erro. Se o próprio JSON do lote estiver incompleto ou tiver IDs inconsistentes, o lote fica para análise manual. Se houver uma interrupção súbita, a próxima execução procura respostas completas nos arquivos e tenta recuperá-las; caso contrário, marca o pedido como `error` para revisão humana. O programa usa o mesmo bloqueio de escrita `dados/queue.lock`.

```bash
python distill.py status
ls -lh dados/raw/eco-*
```

Depois de verificar os arquivos, só se necessário, volta a colocar **um pedido** na fila:

```bash
python distill.py retry --job ID_DO_PEDIDO
python economico.py --limit 4
```

Não repitas indiscriminadamente um lote: a execução anterior pode já ter consumido quota. Não corras `economico.py` simultaneamente com outro comando que altere a fila. Faz cópias de segurança de `dados/` antes de modificações manuais.

## Verificar

```bash
python distill.py status
python monitor.py --port 8766
```

Os dados locais de geração continuam excluídos do GitHub pelo `.gitignore`.

## Recuperar lotes antigos, sem novo consumo

Se um lote antigo deu erro antes de importar as respostas presentes no arquivo:

```bash
python recuperar_economico.py
```

O script verifica os JSON originais de `dados/raw/eco-*.response.json`, cruza os IDs com os manifestos e valida apenas pedidos ainda em `error` provenientes do modo económico. Não chama o modelo, não muda estados e não apaga os originais. Quando encontra respostas válidas, guarda `dados/respostas/recuperacao_economica/respostas_validas.json`.

Para efetivar a importação, depois de ler o relatório:

```bash
python distill.py import dados/respostas/recuperacao_economica/respostas_validas.json --provider codex-economico --teacher gpt-6-luna
python distill.py status
```

Se o ficheiro não for criado, não executes a importação. Pedidos sem resposta ou com JSON inválido ficam em `error` para revisão, sem repetição paga.

## Reparação local conservadora

`python recuperar_economico.py` também tenta corrigir uma citação quando **a mesma sequência de palavras** aparece **uma única vez** na fonte original e só existem diferenças de pontuação/aspas. Preserva o JSON original em `dados/raw/`, documenta cada alteração em `dados/respostas/recuperacao_economica/reparacoes.json` e só exporta pedidos que passam novamente por toda a validação. Não corrige paráfrases, fontes erradas, turnos fora de ordem nem respostas ausentes. **Rever o ficheiro de auditoria antes de importar**, sobretudo quando o texto contém números, frações ou medidas.

## Porquê lotes de dois

Um pedido gera seis exemplos; quatro pedidos obrigam o modelo a produzir até 24 exemplos e respetivas citações numa única resposta estruturada. Nos ensaios observou-se maior frequência de omissões com quatro pedidos, incluindo uma lista vazia. O schema permite `responses: []`, portanto a resposta pode respeitar o schema e falhar as regras de negócio. A instrução foi reforçada, mas a validação continua obrigatória. Subir de `low` para `medium` pode melhorar o seguimento das instruções, mas também pode aumentar os tokens de raciocínio e não garante resolver saídas vazias. Preferir `--batch-size 2 --reasoning-effort low` por omissão; testar `medium` em apenas dois pedidos se necessário, sempre comparando tokens por conversa válida.

## Produção em quantidade

Após confirmar os testes, executar, por exemplo:

```bash
python economico.py --model gpt-6-luna --reasoning-effort low --limit 100 --batch-size 2
```

`--limit 100` permite até 50 chamadas; `--limit 200`, até 100 chamadas. **Os valores são máximos**, não promessas de execução completa: o processo pára ao primeiro lote parcialmente inválido e preserva os pedidos válidos. Uma nova execução seleciona apenas os pendentes e nunca repete automaticamente os erros. A saída vazia `{\"responses\":[]}` é um erro do modelo (ou de cumprimento do formato) mesmo que obedeça ao schema JSON, pelo que não permite importar conversas. O prompt em lote passou a esclarecer que o formato singular documentado é de cada item individual e que o número de respostas deve corresponder ao número de pedidos.
