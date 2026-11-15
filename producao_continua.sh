#!/usr/bin/env bash
# Gera blocos sucessivos de ate 200 pedidos sem ultrapassar paragens de seguranca.
# Executar na raiz do repositorio, com o ambiente Python e Codex autenticado.
set -u
cd "$(dirname "$0")" || exit 1
mkdir -p dados/logs
LOG="dados/logs/producao-$(date +%Y%m%d-%H%M%S)-$$.log"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
echo "Registo da sessao: $LOG" | tee -a "$LOG"
while true; do
    echo "===== Novo bloco: $(date -Is) =====" | tee -a "$LOG"
    : > "$TMP"
    python economico.py \
        --model gpt-6-luna \
        --reasoning-effort low \
        --limit 200 \
        --batch-size 2 \
        --max-consecutive-failures 5 2>&1 | tee -a "$LOG" "$TMP"
    result=${PIPESTATUS[0]}
    if [ "$result" -ne 0 ]; then
        echo "PARAGEM: erro de execucao. Nao repetir automaticamente. Consultar $LOG" | tee -a "$LOG"
        exit "$result"
    fi
    if ! grep -q '^RESUMO: ' "$TMP"; then
        echo "PARAGEM: resumo ausente, verificar log antes de continuar." | tee -a "$LOG"
        exit 1
    fi
    if grep -q 'Motivo de paragem: sem pedidos pendentes elegiveis' "$TMP"; then
        echo "FIM: sem pedidos pendentes elegiveis. Verificar error e manual." | tee -a "$LOG"
        break
    fi
    if grep -q 'Motivo de paragem: limite de falhas consecutivas' "$TMP"; then
        echo "PARAGEM DE SEGURANCA: nao reiniciar sozinho apos falhas repetidas." | tee -a "$LOG"
        break
    fi
    if ! grep -q 'Motivo de paragem: limite de pedidos' "$TMP"; then
        echo "PARAGEM: motivo inesperado, rever o log." | tee -a "$LOG"
        exit 1
    fi
    echo "Bloco concluido. Continuar com os restantes pendentes..." | tee -a "$LOG"
    sleep 5
done
python distill.py status | tee -a "$LOG"
echo "Log final: $LOG"
