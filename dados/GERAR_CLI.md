# Gerar pelo Codex CLI

## 1. Abrir o projeto

Substitui `/caminho/para/tinyLLM` pela pasta onde clonaste o repositório.

```bash
cd /caminho/para/tinyLLM
source .venv/bin/activate
python distill.py status
```

Usa a instalação Codex já existente. O programa confirma a autenticação ChatGPT antes de executar. A configuração do modelo está em config.json; não são necessárias chaves API.

## 2. Gerar

```bash
python distill.py run --limit 10
```

Executa até 10 pedidos pendentes, até 60 conversas. Cada resultado é guardado imediatamente. Reservas manuais não entram nesta execução. O limite não é promessa de quota disponível.

## 3. Ver progresso

Noutro terminal:

```bash
cd /caminho/para/tinyLLM
source .venv/bin/activate
python distill.py status
python monitor.py --port 8766
```

Abre http://127.0.0.1:8766. Logs e respostas estão em dados/raw/. O painel atualiza, mas pausa a atualização quando estás a ler um detalhe.

## 4. Se parar

Os concluídos estão guardados. Vê Estado e Pedidos → erro e eventos. Para quota, aguarda a reposição indicada pelo serviço. Para erro de citação, uma nova geração pode corrigir; a validação não deve ser desligada.

Depois de resolver a causa:

```bash
python distill.py retry
python distill.py run --limit 10
```

retry respeita o máximo de tentativas de config.json. Se não houver erro, basta repetir run: continua nos pendentes. Ctrl+C interrompe e conserva concluídos. Uma execução interrompida abruptamente é recuperada como erro na próxima operação de escrita.

## 5. Exportar

Quando a geração terminar:

```bash
python distill.py export --out dados/exports/candidatos_001
```

candidates.jsonl é o formato completo. sft_train.jsonl e text_train.jsonl são alternativas dos mesmos exemplos. Não juntar os três. Para um treino novo segue notebooks/NOVO_TREINO.md.
