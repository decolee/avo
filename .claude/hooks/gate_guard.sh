#!/usr/bin/env bash
#
# gate_guard.sh — PostToolUse (Write|Edit|MultiEdit): depois de tocar um alvo,
# roda o --selftest DAQUELE alvo e bloqueia se o gate furou.
#
# Existe porque a checagem que importa e a mais facil de adiar. Um gate que
# deixou de rejeitar um mutante nao quebra nada visivelmente: os runs continuam,
# os numeros continuam subindo, e a descoberta vem semanas depois, quando o
# lineage inteiro ja foi construido em cima de uma funcao f que aceitava o
# atalho. Rodar o selftest no instante da edicao e a diferenca entre perder um
# minuto e perder um experimento.
#
# DOIS FUROS DA VERSAO ANTIGA, e o que este arquivo faz no lugar:
#
#   (1) ela olhava para vendor/avo/targets/*/, ou seja, para a COPIA que o
#       bootstrap antigo despejava dentro do harness. Editar o alvo de verdade,
#       em targets/<x>/eval.py, nao disparava absolutamente nada — o hook
#       vigiava um diretorio que ninguem edita. Nao ha mais copia: aqui se olha
#       targets/ na raiz do repositorio.
#
#   (2) ela rodava o selftest de TODOS os alvos a cada Edit|Write, inclusive ao
#       editar um README. Com quatro alvos isso e dezenas de segundos por
#       edicao, e um hook caro e um hook que alguem desliga. O payload do hook
#       traz tool_input.file_path: da para saber QUAL alvo foi tocado e rodar so
#       o dele. Arquivo fora de targets/ sai em silencio, com exit 0.
#
# Contrato de hook: le JSON no stdin, exit 2 devolve o stderr para o agente,
# exit 0 segue em frente.
#
set -uo pipefail

payload="$(cat 2>/dev/null || true)"

# CLAUDE_PROJECT_DIR e o caminho normal; sem ela, deriva do proprio script por
# expansao do bash — `dirname` pode nao existir num PATH minimo, e a versao que
# dependia dele devolvia "/" em silencio.
raiz="${CLAUDE_PROJECT_DIR:-}"
if [ -z "$raiz" ] || [ ! -d "$raiz" ]; then
    aqui="${BASH_SOURCE[0]%/*}"
    [ "$aqui" = "${BASH_SOURCE[0]}" ] && aqui="."
    raiz="$(cd -- "$aqui/../.." 2>/dev/null && pwd)" || raiz="$PWD"
fi

# Mesma extracao em tres camadas do protect_arbiter, duplicada de proposito:
# um hook que depende de um arquivo irmao vira dois modos de falha, e o custo
# de nao carregar e um hook silenciosamente morto.
caminho=""
if command -v jq >/dev/null 2>&1; then
    caminho="$(printf '%s' "$payload" |
        jq -r '(.tool_input.file_path // .tool_input.notebook_path // empty)' 2>/dev/null || true)"
fi
if [ -z "$caminho" ] && command -v python3 >/dev/null 2>&1; then
    caminho="$(printf '%s' "$payload" | python3 -c '
import json, sys
try:
    dados = json.load(sys.stdin)
except Exception:
    raise SystemExit(0)
entrada = dados.get("tool_input") or {}
alvo = entrada.get("file_path") or entrada.get("notebook_path") or ""
if isinstance(alvo, str):
    sys.stdout.write(alvo)
' 2>/dev/null || true)"
fi
if [ -z "$caminho" ]; then
    caminho="$(printf '%s' "$payload" |
        sed -n 's/.*"file_path"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)"
fi

# Sem caminho nao ha alvo a testar. Aqui fail-open e a resposta certa: este hook
# roda DEPOIS da edicao, entao bloquear por JSON malformado so puniria o agente
# por um defeito do harness, sem proteger nada. Quem falha fechado e o
# protect_arbiter, que roda antes.
[ -n "$caminho" ] || exit 0

if [ "${caminho#/}" = "$caminho" ]; then
    base=""
    if command -v python3 >/dev/null 2>&1; then
        base="$(printf '%s' "$payload" | python3 -c '
import json, sys
try:
    dados = json.load(sys.stdin)
except Exception:
    raise SystemExit(0)
valor = dados.get("cwd") or ""
if isinstance(valor, str):
    sys.stdout.write(valor)
' 2>/dev/null || true)"
    fi
    [ -n "$base" ] || base="$raiz"
    caminho="$base/$caminho"
fi
if command -v python3 >/dev/null 2>&1; then
    caminho="$(python3 -c 'import os,sys; sys.stdout.write(os.path.normpath(sys.argv[1]))' \
        "$caminho" 2>/dev/null || printf '%s' "$caminho")"
fi

rel="${caminho#"$raiz"/}"

# Fora de targets/: nada a fazer, sem barulho. Este e o caso comum — a maioria
# esmagadora das edicoes de uma sessao nao toca alvo nenhum.
case "$caminho" in
    */targets/*) ;;
    *) exit 0 ;;
esac

# O diretorio do alvo sai do PROPRIO caminho, nao de `raiz` + palpite: assim o
# hook continua correto mesmo se a raiz do projeto for detectada errado, e
# funciona para um checkout em qualquer lugar do disco.
prefixo="${caminho%%/targets/*}"
resto="${caminho#"$prefixo"/targets/}"
alvo="${resto%%/*}"
dir_alvo="$prefixo/targets/$alvo"
[ -n "$alvo" ] && [ "$alvo" != "$resto" ] || exit 0

# Texto de KB e documentacao nao entra no veredito do gate: o eval.py nao le
# kb/. Rodar o selftest por causa de um .md seria pagar o custo sem comprar
# informacao — que e exatamente o vicio da versao antiga, so que em escala menor.
case "$rel" in
    *.md) exit 0 ;;
esac

# Sem eval.py o diretorio nao e um alvo (pode ser targets/README.md, ou um alvo
# ainda pela metade). Nada a verificar.
if [ ! -f "$dir_alvo/eval.py" ]; then
    exit 0
fi

executor="${PYTHON:-python3}"
command -v "$executor" >/dev/null 2>&1 || exit 0

# O timeout transforma um selftest travado em falha legivel em vez de uma sessao
# pendurada. Se `timeout` nao existir (macOS sem coreutils), roda sem ele.
if command -v timeout >/dev/null 2>&1; then
    saida="$(cd "$dir_alvo" && timeout 300 "$executor" eval.py --selftest 2>&1)"
    codigo=$?
else
    saida="$(cd "$dir_alvo" && "$executor" eval.py --selftest 2>&1)"
    codigo=$?
fi

if [ "$codigo" -eq 0 ]; then
    rejeitados="$(printf '%s\n' "$saida" | grep -c 'FAIL' || true)"
    echo "gate_guard: $alvo ok ($rejeitados mutantes rejeitados) apos editar $rel"
    exit 0
fi

if [ "$codigo" -eq 124 ]; then
    echo "gate_guard: o --selftest de '$alvo' estourou 300s depois de editar $rel." >&2
    echo "Um selftest que nao termina e um gate que nao protege. Investigue antes de seguir." >&2
    exit 2
fi

{
    echo "GATE FUROU em '$alvo' depois de editar $rel (exit $codigo)."
    echo
    printf '%s\n' "$saida" | tail -n 25
    echo
    echo "O --selftest so fica verde quando TODOS os mutantes sao rejeitados. Um mutante"
    echo "aceito e um atalho que a busca vai encontrar sozinha, e a partir dai o score"
    echo "mede o atalho, nao a otimizacao."
    echo
    echo "Reproduza com: cd targets/$alvo && python3 eval.py --selftest"
} >&2
exit 2
