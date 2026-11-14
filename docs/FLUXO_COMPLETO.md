# TinyLLM — fluxo completo de trabalho

**Guia principal do projeto.** Começa aqui quando regressares ao TinyLLM. Os guias especializados estão ligados no fim.

## 1. Objetivo e definição de conclusão

O objetivo é processar **todas as 5 108 receitas atualmente registadas na base de dados**, e não apenas os 5 000 pedidos inicialmente planeados.

Por receita:
- **5 pedidos**, um para cada persona P1–P5;
- **6 conversas** por pedido, cobrindo as capacidades planeadas;
- uma receita só conta como **completa** quando os **5 pedidos das personas estão em `done`**.

A meta teórica é **5 108 receitas × 5 pedidos = 25 540 pedidos** e **25 540 × 6 = 153 240 conversas**. São metas de planeamento; só se tornam resultados depois da validação dos dados. O projeto trabalha atualmente com conversas em **inglês**; C8 (ferramentas) fica para uma iteração futura.

**Fotografia de 14/11/2026 (não é o estado atual permanente):** 5 108 receitas, 1 000 receitas com pedidos, 336 receitas completas, 1 813 pedidos `done`, 2 811 `pending`, 298 `manual`, 78 `error` e 10 878 conversas `auto_valid`. Consulta sempre a base para obter os números atuais.

## 2. O mapa do processo

```text
receitas originais (recipes)
         |
         v
planeamento de 5 personas por receita (jobs)
         |
         +--> pending --> Codex CLI: economico.py --> resposta JSON
         |                                           |
         |                                           v
         |                                validacao estrutural e de citacoes
         |                                           |
         |                                   +-------+--------+
         |                                   |                |
         |                                  done             error
         |                                   |                |
         |                                   v                v
         |                              examples        recuperar / rever /
         |                              auto_valid      retry consciente
         |                                   |
         +--> manual: reservado ao fluxo de chat
                                             |
                                             v
                            auditoria de qualidade e revisao
                                             |
                                             v
                                 exportacao / preparar.py treino
                                             |
                                             v
                                  novo dataset privado no Kaggle
                                             |
                                             v
                                  proximo treino e avaliacao
```

O modo económico só seleciona **`pending`**. Não processa automaticamente `manual`, `error` nem `done`.

## 3. Abrir o projeto e verificar o ambiente

Na raiz da tua cópia do repositório:

```bash
git pull --ff-only
source .venv/bin/activate
python -m unittest -v
codex login status
python distill.py status
```

O código usa Python 3.10+; a geração automática usa o **Codex CLI autenticado via ChatGPT**, sem chaves de API. Não execute dois comandos de geração ao mesmo tempo. Se os testes falharem, **não iniciar a produção** até diagnosticar o motivo.

Os ficheiros locais dentro de `dados/` são dados de trabalho: **`git pull` não os substitui** e não são enviados automaticamente para o GitHub.

## 4. Ver o estado real, incluindo receitas completas

Resumo simples:

```bash
python distill.py status
```

Para medir o objetivo por receitas (consulta apenas de leitura):

```bash
python - <<'PY'
import sqlite3
from pathlib import Path

dbpath = Path("dados/queue.sqlite").resolve()
with sqlite3.connect(dbpath.as_uri() + "?mode=ro", uri=True) as db:
    total = db.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]
    planned = db.execute("SELECT COUNT(DISTINCT recipe_id) FROM jobs").fetchone()[0]
    complete = db.execute("""
        SELECT COUNT(*) FROM (
            SELECT recipe_id
            FROM jobs
            GROUP BY recipe_id
            HAVING COUNT(*) = 5
               AND COUNT(DISTINCT persona) = 5
               AND SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) = 5
        )
    """).fetchone()[0]
    states = db.execute("SELECT status,COUNT(*) FROM jobs GROUP BY status").fetchall()

print(f"Receitas completas: {complete}/{total}")
print(f"Receitas ainda por completar: {total - complete}")
print(f"Receitas com pedidos planeados: {planned}/{total}")
print("Pedidos por estado:", dict(states))
PY
```

**Interpretação:** a contagem de `receitas com pedidos concluídos` do `distill.py status` inclui receitas com apenas *uma* persona concluída; não equivale a receitas completas.

## 5. Expandir o planeamento para todas as receitas

Atualmente só parte das receitas tem pedidos. Para tentar planear as cinco personas das 5 108 receitas:

```bash
python distill.py plan --limit 5108
python distill.py status
```

**Comportamento real do planeador:**
- `--limit 5108` seleciona até 5 108 receitas do catálogo existente, **não cria outras 5 108 receitas**;
- para cada receita elegível, cria somente os pedidos de personas ainda inexistentes;
- pedidos existentes em `done`, `pending`, `manual` ou `error` são preservados; o comando **não corrige** esses estados;
- receitas com texto acima de `max_recipe_chars` em `config.json` (atualmente **14 000**) são **ignoradas**, sem truncar;
- o resumo impresso pelo comando contém `too_long`, `new_jobs` e `target_examples`.

Se `too_long` for maior que zero, **a meta de 5 108 não está ainda garantida**: é preciso tratar essas receitas de forma integral e verificável antes de as dar como planeadas. Não mudar cegamente o limite nem cortar ingredientes ou passos. Se existirem problemas de texto de origem, devem ser auditados separadamente.

Depois de planear, confirmar que existem **25 540 pedidos planeados** para cumprir a meta completa. Se o total for inferior, investigar receitas sem os cinco pedidos.

## 6. Gerar conversas no Codex (fluxo de produção)

Configuração recomendada pelos ensaios efetuados: **GPT-6-Luna, raciocínio low, 2 pedidos por lote**. Medium foi testado, mas não revelou melhoria de taxa de aceitação face a Low nesses ensaios; as receitas testadas não eram idênticas.

```bash
python economico.py \
  --model gpt-6-luna \
  --reasoning-effort low \
  --limit 200 \
  --batch-size 2 \
  --max-consecutive-failures 3
```

Cada execução tenta **até 200 pedidos**, em chamadas de até dois pedidos cada. Um pedido contém seis conversas. O programa guarda respostas válidas e marca pedidos inválidos como `error`; continua após erros isolados e pára por segurança ao atingir três lotes consecutivos com erros. `--max-consecutive-failures 5` é uma alternativa válida, mas poderá gastar mais tokens quando o modelo está sistematicamente a falhar.

Os resultados aparecem em `dados/raw/eco-*.manifest.json`, `*.response.json`, `*.summary.json`, `*.events.jsonl` e `*.stderr.txt`. **Tokens reportados não equivalem a custo financeiro nem a quota disponível.** Repetir o comando continua nos pendentes, sem repetir automaticamente `done` ou `error`.

A geração pode demorar várias sessões e requer disponibilidade do Codex; não existe uma execução permanente automática instalada por este guia.

## 6A. Deixar a produção contínua durante a noite (Linux)

Depois de `git pull --ff-only`, com o ambiente Python ativo e `codex login status` válido:

```bash
bash producao_continua.sh
```

O script liga automaticamente vários blocos de **até 200 pedidos** em `low`, lotes de **2**, até deixar de haver pendentes elegíveis. Guarda um log em `dados/logs/producao-AAAAmmdd-HHMMSS.log`. **Pára sem reiniciar** se houver três tipos de situação: falha de execução/infraestrutura, **5 lotes consecutivos com erros** ou ausência de pedidos pendentes. Um erro isolado não obriga à paragem. Não tenta automaticamente os `error` nem os `manual`; esses são tratados no passo seguinte.

Se deixares o PC sem vigilância, **desativa a suspensão automática**, mantém o computador ligado à corrente e não inicies outros geradores. Para acompanhar noutra janela, usa `python distill.py status`. Deixar o programa aberto não garante que o Codex mantenha quota ou autenticação durante toda a noite; quando estes falharem o script interrompe, preservando o trabalho.

Para interromper conscientemente, usa **Ctrl+C** na janela que executa o script. Nunca apagues `dados/queue.sqlite` nem os ficheiros `dados/raw`.

## 7. Resolver erros e pedidos manuais — sem perder trabalho

Estados dos pedidos:
- **`pending`**: elegível para o gerador económico;
- **`running`**: foi iniciado; após interrupção, verificar recuperação e arquivos;
- **`done`**: resposta validada e guardada;
- **`error`**: faltou resposta, falhou citação, formato ou execução;
- **`manual`**: reservado ao fluxo por chat; **não é processado** pelo modo económico.

Primeiro, procurar resultados aproveitáveis **sem chamar o modelo**:

```bash
python recuperar_economico.py
```

O recuperador **não altera a fila automaticamente**. Se gerar `dados/respostas/recuperacao_economica/respostas_validas.json`, rever o relatório e as reparações antes de importar:

```bash
python distill.py import \
  dados/respostas/recuperacao_economica/respostas_validas.json \
  --provider codex-economico \
  --teacher gpt-6-luna
```

**Não executar a importação se o ficheiro não existir ou não tiver sido revisto.** Reparações conservadoras apenas: nunca atribuir uma citação de outra receita por suposição, nem trocar um `job_id` desconhecido pelo ID esperado.

Para voltar a tentar **um pedido com erro**, após inspeção:

```bash
python distill.py retry --job ID_DO_PEDIDO
```

`retry` respeita `max_attempts` do `config.json` (atualmente 3); não há garantia de recuperar pedidos que atingiram esse limite. O comando `python distill.py retry` **sem `--job`** pode repor múltiplos pedidos em erro: evitar usá-lo sem antes rever o conjunto.

**Reservas manuais:** o comando `retry --job` também permite converter um pedido `manual` individual em `pending`, desde que esteja abaixo de `max_attempts`, mas é imprescindível confirmar primeiro que não existe resposta manual ainda por importar. Não converter em massa as 298 reservas antigas sem inventário. Assim que um pedido voltar a `pending`, o `economico.py` pode selecioná-lo.

**Para realmente concluir todas as receitas**, será preciso tratar ainda os `error` persistentes, os `manual` e quaisquer receitas não planeadas. O fluxo atual **não garante sozinho 100% de conclusão**.

## 8. Auditar qualidade durante a expansão

```bash
python auditar_dataset.py --per-cell 2 --seed 42
```

O comando percorre exemplos gravados e escolhe uma amostra estratificada de até **70 conversas** (duas para cada par persona/capacidade C1–C7). Cria:

- `dados/auditoria/resumo.json` — métricas e alertas mecânicos;
- `dados/auditoria/amostra.jsonl` — amostra para processamento;
- `dados/auditoria/amostra_para_revisao.md` — conversa, receita e citações lado a lado.

`auto_valid` significa que passou validações automáticas de formato e citações, **não que a resposta está factualmente correta**. Rever especialmente ingredientes, quantidades, tempos, temperaturas, alergénios, segurança alimentar, naturalidade, utilidade e continuidade C6.

Não reduzir o controlo de fontes para aumentar artificialmente a taxa de sucesso.

## 9. Monitorizar no navegador

```bash
python monitor.py --port 8766
```

Abrir **http://127.0.0.1:8766**. Em **Visão geral** vê-se a fila, as conversas e a cobertura das personas; em **Pedidos**, os erros; em **Respostas**, as conversas e evidências; em **Instruções**, este guia e os documentos específicos.

O painel pode ler enquanto o gerador funciona; **não executar operações de escrita concorrentes**.

## 10. Preparar o próximo treino (quando o dataset estiver pronto)

Não é necessário preparar uma demo agora. Para o próximo treino, seguir a estratégia documentada de **reutilizar a validação anterior** e evitar misturar receitas relacionadas entre treino e avaliação.

```bash
python preparar.py treino --validation dados/validation_v01.jsonl --nome culinario_v03
```

Este comando **requer** a existência de `dados/validation_v01.jsonl` da experiência anterior e cria uma versão imutável dos dados (não sobrescreve versões). Confirmar o relatório e o número de exemplos antes de atualizar o dataset privado no Kaggle.

Não confundir `python distill.py export` (candidatos e formatos alternativos) com `preparar.py treino` (prepara a versão específica com validação separada). Para os detalhes, consultar [Novo treino no Kaggle](../notebooks/NOVO_TREINO.md).

## 11. Segurança e backups

- `dados/queue.sqlite` é a base principal. **Não apagar** para resolver erros.
- Antes de operações de recuperação em massa, planeamento em larga escala ou alterações de código: parar o gerador e fazer backup de `dados/`.
- Não gerar em paralelo por dois terminais, outra automação ou OpenClaw.
- Não publicar `dados/` ou `modelos/` no GitHub. O `.gitignore` deve continuar a protegê-los.
- Conservar `dados/raw/` para auditoria e recuperação de chamadas já efetuadas.
- Verificar `python -m unittest -v` após atualizar o código.

## 12. Onde ler mais (índice curto)

| Assunto | Documento |
|---|---|
| Visão do projeto | [README principal](../README.md) |
| Base de dados, estados e planeamento | [Dados e estado](../dados/README.md) |
| Geração em lotes com Luna | [Geração económica](GERACAO_ECONOMICA.md) |
| Geração via linha de comandos alternativa | [Codex CLI](../dados/GERAR_CLI.md) |
| Geração via ChatGPT | [Fluxo de chat](../dados/GERAR_CHAT.md) |
| Auditoria de qualidade | [Auditoria do dataset](AUDITORIA_DATASET.md) |
| Treino e validação | [Novo treino no Kaggle](../notebooks/NOVO_TREINO.md) |
| Pesos e resultados | [Modelos](../modelos/README.md) |

**Regra simples para retomar:** consultar estado → verificar receitas completas → planear receitas em falta → gerar pendentes → recuperar erros/manuais → auditar → preparar treino.
