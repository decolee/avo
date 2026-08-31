#!/usr/bin/env bash
#
# bootstrap.sh — deixa uma maquina limpa pronta para rodar a bancada.
#
# Rode da raiz do repositorio, quantas vezes quiser: cada passo checa antes de
# agir, entao a segunda execucao e barata e nao destroi nada.
#
#   ./bootstrap.sh                 setup completo
#   ./bootstrap.sh --no-tests      pula a suite do upstream (mais rapido)
#   ./bootstrap.sh --no-install    so verifica; nao chama pip
#   ./bootstrap.sh --force-data    regenera os datasets do zero
#
# TRES DEFEITOS DA VERSAO ANTIGA, e o que este arquivo faz no lugar:
#
#   (a) clonava o harness sem fixar commit. O ambiente mudava sozinho: o
#       scoring, a politica de commit e o formato do AVO_RESULT vivem no
#       upstream, e se ele anda debaixo dos alvos dois runs deixam de ser
#       comparaveis. Agora o commit vem de vendor/avo.lock e o checkout e feito
#       nele; divergencia entre o lock e o HEAD local vira aviso alto.
#
#   (b) copiava targets/ para dentro de vendor/avo/targets/ a cada execucao.
#       Era desnecessario E perigoso. Desnecessario porque o harness resolve
#       alvos em Path.cwd()/targets ANTES dos internos (vendor/avo/src/avo/
#       config.py::resolve_target) — rodando da raiz do repo, os nossos alvos
#       sao achados direto. Perigoso porque o agente editava a copia e o
#       original ficava para tras, ou vice-versa, e ninguem sabia qual eval.py
#       tinha julgado o run. Este script NAO copia nada.
#
#   (c) regenerava os datasets sempre. Os make_data.py ja sao idempotentes:
#       comparam com o dataset.lock.json e so escrevem o que falta. Aqui eles
#       sao chamados sem --force, e regenerar de verdade e opt-in.
#
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"
LOCK="$ROOT/vendor/avo.lock"
VENDOR="$ROOT/vendor/avo"

DO_INSTALL=1
DO_TESTS=1
DATA_ARGS=()

# ------------------------------------------------------------------ saida

hr() { printf '%s\n' "------------------------------------------------------------------"; }
passo() { hr; printf '==> %s\n' "$*"; }
info() { printf '    %s\n' "$*"; }
aviso() {
    hr
    printf 'AVISO: %s\n' "$1"
    shift
    for linha in "$@"; do printf '       %s\n' "$linha"; done
    hr
}
morre() {
    printf '\n' >&2
    printf 'ERRO: %s\n' "$1" >&2
    shift
    for linha in "$@"; do printf '      %s\n' "$linha" >&2; done
    printf '\n' >&2
    exit 1
}

uso() {
    cat <<'AJUDA'
bootstrap.sh — deixa uma maquina limpa pronta para rodar a bancada.

Rode da raiz do repositorio, quantas vezes quiser: cada passo checa antes de
agir, entao a segunda execucao e barata e nao destroi nada.

  ./bootstrap.sh                 setup completo
  ./bootstrap.sh --no-tests      pula a suite do upstream (mais rapido)
  ./bootstrap.sh --no-install    so verifica; nao chama pip
  ./bootstrap.sh --force-data    regenera os datasets do zero

Variaveis de ambiente:
  PYTHON=/caminho/python3        interpretador a usar
  AVO_LAB_ALLOW_DIRTY_VENDOR=1   segue mesmo com vendor/avo alterado localmente
AJUDA
    exit 0
}

for arg in "$@"; do
    case "$arg" in
        --no-install) DO_INSTALL=0 ;;
        --no-tests) DO_TESTS=0 ;;
        --force-data) DATA_ARGS=(--force) ;;
        -h | --help) uso ;;
        *) morre "argumento desconhecido: $arg" "rode ./bootstrap.sh --help" ;;
    esac
done

# ------------------------------------------------- 0. o que precisa existir

passo "Verificando o ambiente"

command -v git >/dev/null 2>&1 || morre "git nao encontrado no PATH."
command -v "$PY" >/dev/null 2>&1 ||
    morre "interpretador '$PY' nao encontrado." \
        "Aponte outro com: PYTHON=/caminho/para/python3 ./bootstrap.sh"

"$PY" - <<'PYCHECK' || morre "Python muito antigo." "A bancada usa 3.11; o minimo declarado no pyproject.toml e 3.10."
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PYCHECK
info "python: $("$PY" -c 'import platform,sys; print(platform.python_version(), sys.executable)')"
info "git:    $(git --version)"

[ -f "$ROOT/pyproject.toml" ] || morre "rode este script da raiz do repositorio (nao achei pyproject.toml em $ROOT)."

# ----------------------------------------------------- 1. harness upstream

passo "Harness upstream (vendor/avo)"

[ -f "$LOCK" ] || morre "vendor/avo.lock nao existe." \
    "Ele fixa o commit auditado do harness e e o unico ponteiro versionado para ele." \
    "Sem lock, nao ha ambiente reprodutivel — e este script se recusa a inventar um."

# Le 'chave = valor' do lock ignorando comentarios e espacos.
campo_do_lock() {
    sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*\([^[:space:]#]*\).*/\1/p" "$LOCK" | head -n 1
}

REPO="$(campo_do_lock repo)"
COMMIT="$(campo_do_lock commit)"

[ -n "$REPO" ] || morre "vendor/avo.lock nao declara 'repo = <url>'."
printf '%s' "$COMMIT" | grep -Eq '^[0-9a-f]{40}$' ||
    morre "vendor/avo.lock nao declara um commit valido (40 hex): '${COMMIT}'." \
        "Um commit curto ou um nome de branch nao serve: branch se move."

info "repo:   $REPO"
info "commit: $COMMIT"

if [ -e "$VENDOR" ] && [ ! -d "$VENDOR/.git" ]; then
    morre "$VENDOR existe mas nao e um clone git." \
        "Remova-o (rm -rf vendor/avo) e rode ./bootstrap.sh de novo."
fi

if [ ! -d "$VENDOR/.git" ]; then
    info "clonando (primeira vez)..."
    git clone --quiet "$REPO" "$VENDOR" ||
        morre "falhou ao clonar $REPO." \
            "Sem rede? Um clone manual em vendor/avo tambem serve; o script so precisa que" \
            "o commit $COMMIT exista la dentro."
fi

# `--untracked-files=no` nao e frouxidao: e o que faz este script ser idempotente
# de verdade. O passo 4 roda a suite do upstream, o pytest escreve
# vendor/avo/tests/__pycache__/, e um `status --porcelain` sem essa flag passa a
# reportar "?? tests/__pycache__/" — a segunda execucao do bootstrap abortava
# acusando alteracao local que ninguem fez. Descoberto rodando duas vezes
# seguidas. O que importa para reprodutibilidade e arquivo RASTREADO modificado;
# bytecode nao muda o que o harness faz.
SUJO="$(git -C "$VENDOR" status --porcelain --untracked-files=no 2>/dev/null || true)"
HEAD_ATUAL="$(git -C "$VENDOR" rev-parse HEAD 2>/dev/null || echo "?")"

if [ -n "$SUJO" ]; then
    if [ "${AVO_LAB_ALLOW_DIRTY_VENDOR:-0}" = "1" ]; then
        aviso "vendor/avo tem alteracoes locais e AVO_LAB_ALLOW_DIRTY_VENDOR=1 esta setado." \
            "Seguindo SEM fixar o commit. O ambiente NAO e reprodutivel:" \
            "qualquer numero medido agora vale so nesta maquina."
    else
        morre "vendor/avo tem alteracoes locais nao commitadas:" \
            "$(printf '%s' "$SUJO" | head -n 5 | sed 's/^/        /')" \
            "" \
            "O harness e codigo de terceiro fixado por commit; editar a copia local faz o" \
            "laboratorio medir uma coisa e o lock descrever outra." \
            "Descarte com: git -C vendor/avo checkout -- . && git -C vendor/avo clean -fd" \
            "Ou, se a alteracao e deliberada e temporaria: AVO_LAB_ALLOW_DIRTY_VENDOR=1 ./bootstrap.sh"
    fi
elif [ "$HEAD_ATUAL" != "$COMMIT" ]; then
    aviso "vendor/avo esta em $HEAD_ATUAL, o lock pede $COMMIT." \
        "Fazendo checkout do commit do lock. Se voce queria SUBIR o harness," \
        "edite vendor/avo.lock (nao o checkout) e rode ./bootstrap.sh de novo."
    git -C "$VENDOR" fetch --quiet origin "$COMMIT" 2>/dev/null ||
        git -C "$VENDOR" fetch --quiet --all --tags 2>/dev/null || true
    git -C "$VENDOR" cat-file -e "$COMMIT^{commit}" 2>/dev/null ||
        morre "o commit $COMMIT nao existe em $VENDOR nem apos o fetch." \
            "O lock aponta para um commit que este remoto nao tem. Confira a url e o hash."
    git -C "$VENDOR" checkout --quiet --detach "$COMMIT" ||
        morre "falhou o checkout de $COMMIT em $VENDOR."
    info "checkout ok: $(git -C "$VENDOR" rev-parse --short HEAD)"
else
    info "ja no commit do lock; nada a fazer."
fi

# O que NAO acontece aqui, e por que: nenhuma copia de targets/ para dentro de
# vendor/avo/targets/. `resolve_target` procura em Path.cwd()/targets primeiro,
# entao rodar da raiz basta. A conferencia abaixo prova isso em vez de afirmar.

# ---------------------------------------------------------- 2. instalacao

if [ "$DO_INSTALL" = "1" ]; then
    passo "Instalando (editavel: harness + labkit)"
    if [ -z "${VIRTUAL_ENV:-}" ] && [ "$(id -u)" != "0" ]; then
        info "nenhum virtualenv ativo; o pip vai instalar no ambiente corrente."
    fi
    "$PY" -m pip install --quiet --editable "$VENDOR" ||
        morre "falhou 'pip install -e vendor/avo'." \
            "Se o erro fala em permissao ou 'externally-managed-environment', crie um venv:" \
            "  python3 -m venv .venv && . .venv/bin/activate && ./bootstrap.sh"
    "$PY" -m pip install --quiet --editable "$ROOT[dev]" ||
        morre "falhou 'pip install -e .[dev]' na raiz do repositorio."
    info "avo:    $("$PY" -c 'import avo, pathlib; print(pathlib.Path(avo.__file__).parent)' 2>/dev/null || echo '?')"
    info "labkit: $("$PY" -c 'import labkit, pathlib; print(pathlib.Path(labkit.__file__).parent)' 2>/dev/null || echo '?')"
else
    passo "Instalacao pulada (--no-install)"
fi

# ------------------------------------------------------------- 3. datasets

passo "Datasets congelados"

mapfile -t GERADORES < <(find "$ROOT/targets" -mindepth 2 -maxdepth 2 -name make_data.py | sort)
[ "${#GERADORES[@]}" -gt 0 ] || morre "nenhum targets/*/make_data.py encontrado."

for gerador in "${GERADORES[@]}"; do
    alvo="$(basename "$(dirname "$gerador")")"
    info "$alvo"
    "$PY" "$gerador" ${DATA_ARGS[@]+"${DATA_ARGS[@]}"} 2>&1 | sed 's/^/      /' ||
        morre "make_data.py do alvo '$alvo' falhou." \
            "Sem dataset nao ha gate: o eval.py nao tem contra o que julgar."
done

# --------------------------------------------------- 4. testes do upstream

if [ "$DO_TESTS" = "1" ]; then
    passo "Suite do harness upstream"
    if [ -d "$VENDOR/tests" ] && "$PY" -c 'import pytest' 2>/dev/null; then
        "$PY" -m pytest "$VENDOR/tests" -q --no-header 2>&1 | tail -n 5 ||
            morre "a suite do upstream falhou no commit $COMMIT." \
                "Isso e do harness, nao dos alvos: nao adianta mexer em targets/." \
                "Confira se o commit do lock e mesmo o auditado."
    else
        aviso "pulando a suite do upstream (sem vendor/avo/tests ou sem pytest)."
    fi
else
    passo "Suite do upstream pulada (--no-tests)"
fi

# ------------------------------------------- 5. o gate de todos os alvos

passo "Gate de todos os alvos (--selftest)"

mapfile -t AVALIADORES < <(find "$ROOT/targets" -mindepth 2 -maxdepth 2 -name eval.py | sort)
[ "${#AVALIADORES[@]}" -gt 0 ] || morre "nenhum targets/*/eval.py encontrado."

FALHOS=()
for avaliador in "${AVALIADORES[@]}"; do
    alvo="$(basename "$(dirname "$avaliador")")"
    if saida="$("$PY" "$avaliador" --selftest 2>&1)"; then
        mutantes="$(printf '%s\n' "$saida" | grep -c 'mutante .*FAIL\|FAIL  mutante' || true)"
        info "ok   $alvo ($mutantes mutantes rejeitados)"
    else
        FALHOS+=("$alvo")
        printf '    FALHA %s\n' "$alvo"
        printf '%s\n' "$saida" | tail -n 12 | sed 's/^/          /'
    fi
done

if [ "${#FALHOS[@]}" -gt 0 ]; then
    morre "o gate furou em: ${FALHOS[*]}" \
        "Um alvo cujo --selftest nao fica verde nao pode ser usado: o gate e a unica coisa" \
        "que separa otimizacao de reward hacking, e um gate que aceita mutante nao separa nada."
fi

# Prova de (b), rodada em vez de afirmada: `avo targets` da raiz tem que listar
# CADA alvo nosso, sem que nada tenha sido copiado para dentro de vendor/. A
# listagem inclui tambem os alvos internos do upstream — o que interessa aqui e
# que os nossos aparecam junto.
passo "O harness enxerga os alvos sem copia (prova do defeito (b))"

if ! "$PY" -c 'import avo' 2>/dev/null; then
    info "harness nao importavel neste ambiente; pulando a conferencia."
elif ! listagem="$(cd "$ROOT" && "$PY" -m avo targets 2>/dev/null)"; then
    aviso "'python3 -m avo targets' falhou; nao deu para conferir a resolucao de alvos."
else
    invisiveis=()
    for avaliador in "${AVALIADORES[@]}"; do
        alvo="$(basename "$(dirname "$avaliador")")"
        printf '%s\n' "$listagem" | grep -Eq "^[[:space:]]*${alvo}([[:space:]]|$)" ||
            invisiveis+=("$alvo")
    done
    if [ "${#invisiveis[@]}" -gt 0 ]; then
        morre "o harness NAO enxerga: ${invisiveis[*]}" \
            "Rodando da raiz, resolve_target procura em Path.cwd()/targets antes dos alvos" \
            "internos. Se um alvo nosso nao aparece, ou o target.yaml nao carrega, ou este" \
            "script foi rodado de outro diretorio. A solucao NAO e copiar para vendor/."
    fi
    info "${#AVALIADORES[@]} alvo(s) nosso(s) visiveis da raiz, sem copia nenhuma."
fi

hr
cat <<'FIM'
Ambiente pronto.

Proximo comando:

    make run TARGET=etl_agg

Ele abre um run e imprime o primeiro prompt de variacao. Cole-o numa sessao do
Claude Code e siga docs/RUNBOOK.md a partir da Sessao 0.

Lembre: `avo submit` roda da RAIZ, com --run runs/<id>. De dentro do run dir ele
falha (Falha 3). `make submit RUN=runs/<id> M="resumo"` faz isso certo.
FIM
