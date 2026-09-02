#!/usr/bin/env bash
# Vigia do programa: relanca se ele morrer, dentro da vida deste container.
#
# Existe porque a plataforma recicla o container, e cada reciclagem deixava o
# programa parado ate eu perceber. Um restart do container mata este vigia
# tambem — nao ha como evitar isso daqui — mas as mortes do processo que NAO sao
# reciclagem (que ja aconteceram: a Fase 2A morreu uma vez em silencio, sem
# traceback, com disco e memoria folgados) passam a ser recuperadas em segundos.
#
#   uso: vigia.sh <log> <minutos>
set -u
LOG="${1:?log}"
MIN="${2:-14}"
RAIZ="$(cd "$(dirname "$0")/../.." && pwd)"
vivo() { ps -eo args --no-headers | grep -q "^python3 experiments/ablacao/programa.py"; }

cd "$RAIZ"
for ((i = 0; i < MIN * 2; i++)); do
  if ! vivo; then
    echo "$(date +%H:%M:%S) vigia: programa morto, relancando" >> "$LOG"
    setsid nohup python3 experiments/ablacao/programa.py >> "$LOG" 2>&1 < /dev/null &
    disown
    sleep 10
  fi
  sleep 30
done
