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

Depois, o comando `python economico.py` utiliza por omissão o modelo `gpt-6-luna`, raciocínio `low`, no máximo 20 pedidos e 4 por lote. Para alterar o raciocínio, usa `--reasoning-effort` (low, medium, high ou xhigh). Não arranca automaticamente um segundo bloco de 20. Para personalizar o ensaio, usa `--limit` (1 a 20) e `--batch-size` (1 a 4).

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

Os resultados são validados antes da importação. Se um lote falhar, pára sem regeneração automática. Se houver uma interrupção súbita, a próxima execução procura respostas completas nos arquivos e tenta recuperá-las; caso contrário, marca o pedido como `error` para revisão humana. O programa usa o mesmo bloqueio de escrita `dados/queue.lock`.

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
