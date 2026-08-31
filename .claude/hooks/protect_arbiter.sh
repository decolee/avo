#!/usr/bin/env bash
#
# protect_arbiter.sh — PreToolUse (Write|Edit|MultiEdit): torna mecanica a regra
# inviolavel do CLAUDE.md, "nunca edite o eval.py para um candidato passar".
#
# Enquanto essa regra e so prosa, ela vale exatamente ate o momento em que o
# candidato falha no gate e a edicao de uma tolerancia parece um detalhe. O
# problema nao e ma fe: e que afrouxar o arbitro tem retorno imediato e custo
# invisivel. Quem paga e a busca inteira, que passa a otimizar uma funcao que
# nao mede mais o que dizia medir.
#
# O que este hook bloqueia:
#   targets/<alvo>/eval.py    a funcao f — o arbitro
#   labkit/**                 a biblioteca que os arbitros compartilham:
#                             medicao, gate, mutantes, congelamento de dataset
#
# A valvula de escape e explicita e documentada, porque mudanca legitima no
# arbitro existe e e comum — adicionar um mutante, corrigir um bug do gate,
# apertar uma tolerancia frouxa:
#
#   AVO_LAB_ALLOW_ARBITER_EDIT=1
#
# Com ela setada o hook libera e registra a passagem no stderr. A ideia nao e
# impedir a edicao: e impedir a edicao DISTRAIDA, e obrigar quem edita a dizer
# em voz alta que sabe o que esta fazendo.
#
# Contrato de hook: le JSON no stdin, exit 2 bloqueia e devolve o stderr para o
# agente, exit 0 libera.
#
set -uo pipefail

payload="$(cat 2>/dev/null || true)"

# ------------------------------------------------------------------ raiz
# CLAUDE_PROJECT_DIR e o caminho normal; a derivacao a partir do proprio script
# e o plano B para quando o hook e chamado fora do Claude Code (um teste no
# terminal, por exemplo) ou por uma versao que nao exporta a variavel.
#
# A derivacao usa expansao do bash e nao `dirname`: um PATH minimo sem coreutils
# fazia o fallback devolver "/" silenciosamente, e um hook que calcula a raiz
# errada nao bloqueia nada — falhava aberto exatamente onde precisa falhar
# fechado. Descoberto alimentando o hook com PATH restrito.
raiz="${CLAUDE_PROJECT_DIR:-}"
if [ -z "$raiz" ] || [ ! -d "$raiz" ]; then
    aqui="${BASH_SOURCE[0]%/*}"
    [ "$aqui" = "${BASH_SOURCE[0]}" ] && aqui="."
    raiz="$(cd -- "$aqui/../.." 2>/dev/null && pwd)" || raiz="$PWD"
fi

# --------------------------------------------------------------- extracao
# Tres tentativas em ordem de confiabilidade. jq e python3 tratam certo caminho
# com espaco, com acento e com barra invertida; o sed final e so para nao ficar
# cego se nenhum dos dois existir na maquina.
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

# JSON malformado ou sem file_path. Fail-open seria o normal para um hook, mas
# este protege o arbitro: entao antes de liberar, varre o payload cru atras de
# um caminho suspeito. Se o texto menciona um eval.py de alvo ou labkit/, o
# hook bloqueia mesmo sem ter conseguido interpretar o JSON — errar bloqueando
# custa uma variavel de ambiente, errar liberando custa a validade do run.
if [ -z "$caminho" ]; then
    if printf '%s' "$payload" | grep -Eq 'targets/[^"/]+/eval\.py|(^|[^a-z])labkit/'; then
        if [ "${AVO_LAB_ALLOW_ARBITER_EDIT:-0}" = "1" ]; then
            exit 0
        fi
        echo "protect_arbiter: nao consegui interpretar o JSON do hook, mas o payload menciona" >&2
        echo "um arbitro (targets/*/eval.py ou labkit/). Bloqueando por precaucao." >&2
        echo "Se a edicao e legitima: AVO_LAB_ALLOW_ARBITER_EDIT=1" >&2
        exit 2
    fi
    exit 0
fi

# ----------------------------------------------------------- normalizacao
# Caminho relativo e resolvido contra o cwd que o proprio payload declara —
# nao contra o cwd do hook, que nao e o mesmo processo.
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
    # normpath e nao realpath: o arquivo pode ainda nao existir (Write), e
    # realpath de caminho inexistente devolve vazio em algumas versoes.
    caminho="$(python3 -c 'import os,sys; sys.stdout.write(os.path.normpath(sys.argv[1]))' \
        "$caminho" 2>/dev/null || printf '%s' "$caminho")"
fi

rel="${caminho#"$raiz"/}"

# ------------------------------------------------------------- veredito
# Os padroes aparecem duas vezes, ancorados e nao ancorados. O par ancorado
# (`targets/...`) casa o caso normal, com a raiz detectada certo. O par com
# `*/` na frente e a rede: se a raiz for detectada errada, `rel` continua
# absoluto e o padrao ancorado nao casaria — e o hook liberaria a edicao do
# arbitro justamente na situacao em que ele esta mais confuso.
protegido=""
case "$rel" in
    targets/*/eval.py | */targets/*/eval.py)
        alvo_tocado="${rel##*targets/}"
        alvo_tocado="${alvo_tocado%%/*}"
        protegido="o avaliador (a funcao f) do alvo '$alvo_tocado'"
        ;;
    labkit/* | */labkit/*)
        protegido="labkit/, a biblioteca compartilhada pelos avaliadores"
        ;;
esac

[ -n "$protegido" ] || exit 0

if [ "${AVO_LAB_ALLOW_ARBITER_EDIT:-0}" = "1" ]; then
    echo "protect_arbiter: liberado por AVO_LAB_ALLOW_ARBITER_EDIT=1 -> $rel" >&2
    echo "  Diga no commit por que a mudanca no arbitro era legitima, e rode 'make selftest'." >&2
    exit 0
fi

cat >&2 <<MENSAGEM
BLOQUEADO: $rel e $protegido.

Editar o arbitro para um candidato passar e reward hacking, nao otimizacao: o
numero sobe e para de significar alguma coisa. Esta e a regra inviolavel do
CLAUDE.md, e este hook e ela deixando de ser so prosa.

Se o candidato falhou no gate, a resposta e mudar o candidato. A mensagem do
gate diz exatamente qual contrato foi violado — ela e o diagnostico, nao o
obstaculo.

Se a mudanca no arbitro E legitima (adicionar um mutante, corrigir um bug do
gate, apertar uma tolerancia frouxa), a valvula de escape e explicita:

    AVO_LAB_ALLOW_ARBITER_EDIT=1

Depois de mexer no arbitro: 'make selftest' verde, e o commit precisa dizer por
que a mudanca era legitima.
MENSAGEM
exit 2
