"""Fixtures compartilhadas da suíte do laboratório.

A suíte tem duas metades com custos muito diferentes. `test_labkit.py` é unidade
pura e roda em milissegundos; o resto chama os `eval.py` de verdade por
subprocesso, porque é assim que o harness os chama e é a única forma de provar
que o contrato vale ponta a ponta — um `import` do módulo não exercitaria o
`argparse`, nem o `sys.path`, nem o formato do stdout.

Três decisões deste arquivo, todas por causa desse custo:

*Um `--selftest` por alvo, não um por teste.* `test_gate_teeth.py` e
`test_target_contract.py` olham para a mesma saída por motivos diferentes.
Rodar o subprocesso duas vezes dobraria o tempo da suíte sem descobrir nada, e o
`--selftest` do `dedupe_match` sozinho leva ~7 s (um dos mutantes existe
justamente para estourar o orçamento de tempo). O cache é indexado por
`(alvo, argumentos)` e vive pela sessão inteira.

*Dado ausente pula, dado corrompido falha.* Os datasets são gerados e não vão
para o git. Numa máquina limpa eles simplesmente não existem, e uma suíte que
falha vermelho nessa situação treina o time a ignorar vermelho. Já um arquivo
que existe e não bate com o lock é um bug de verdade — o gerador mudou — e
falha. `datakit.verify_lock` distingue os dois casos na mensagem, e é dela que
esta decisão é lida.

*`sys.executable`, não `"python3"`.* O `target.yaml` declara `python3` porque é
o que o harness invoca; aqui interessa rodar no mesmo interpretador que roda o
pytest, senão a suíte passa contra um Python que ninguém está testando.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TARGETS_DIR = ROOT / "targets"

#: Onde o harness upstream vive quando não está instalado no ambiente.
VENDOR_SRC = ROOT / "vendor" / "avo" / "src"

#: Teto por chamada de `eval.py`. Generoso de propósito: o objetivo é
#: transformar um travamento em falha legível, não policiar desempenho — disso
#: cuida `--budget`.
EVAL_TIMEOUT_S = 900


# ------------------------------------------------------------- descoberta


def discover_targets() -> list[Path]:
    """Todo diretório sob `targets/` que declara um `target.yaml`.

    A descoberta é por varredura e não por lista fixa: um alvo novo entra na
    suíte no instante em que ganha um `target.yaml`, sem que ninguém precise
    lembrar de registrá-lo. É o que faz a disciplina valer para o alvo futuro,
    que é o ponto destes testes.
    """
    if not TARGETS_DIR.is_dir():
        return []
    return sorted((p.parent for p in TARGETS_DIR.glob("*/target.yaml")), key=lambda p: p.name)


TARGETS = discover_targets()


def target_id(path: Path) -> str:
    """Id de parametrização: o nome do alvo, para o `-k` ficar utilizável."""
    return path.name


#: Açúcar para `@pytest.mark.parametrize` — a mesma parametrização em três
#: módulos, escrita uma vez.
parametrize_targets = pytest.mark.parametrize("target", TARGETS, ids=target_id)


# ------------------------------------------------------- execução de eval.py


@dataclass(frozen=True)
class EvalRun:
    """O resultado bruto de uma chamada de `eval.py`, mais o que se lê dele."""

    exit_code: int
    stdout: str
    stderr: str
    argv: tuple[str, ...]

    def __iter__(self):
        """Desempacota como `(exit, stdout, stderr)`."""
        return iter((self.exit_code, self.stdout, self.stderr))

    def dump(self, limit: int = 2000) -> str:
        """Um bloco pronto para ir na mensagem de falha do assert.

        Um teste de subprocesso que falha dizendo só `assert 1 == 0` obriga quem
        lê a reproduzir o comando na mão. Isto entrega a saída junto.
        """
        return (
            f"\ncomando: {' '.join(self.argv)}"
            f"\nexit: {self.exit_code}"
            f"\nstdout:\n{self.stdout[-limit:]}"
            f"\nstderr:\n{self.stderr[-limit:]}"
        )


_RUN_CACHE: dict[tuple[str, tuple[str, ...]], EvalRun] = {}


def run_eval(
    target: Path, *args: str, cache: bool = True, timeout: int = EVAL_TIMEOUT_S
) -> EvalRun:
    """Roda `eval.py` do alvo com os argumentos dados, do jeito que o harness roda.

    `cwd` é a raiz do repositório e o caminho do avaliador é absoluto, que é
    exatamente o que `evaluate.command` produz depois da substituição de
    `{target}`. Rodar de dentro do diretório do alvo esconderia uma dependência
    de diretório corrente — e uma dessas já custou um ciclo de depuração
    (Falha 3 do plano).

    `cache=False` para chamadas que dependem de estado externo (um `--workdir`
    em tmpdir, por exemplo, que muda a cada teste).
    """
    key = (target.name, args)
    if cache and key in _RUN_CACHE:
        return _RUN_CACHE[key]

    argv = (sys.executable, str(target / "eval.py"), *args)
    proc = subprocess.run(
        argv,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    run = EvalRun(proc.returncode, proc.stdout, proc.stderr, argv)
    if cache:
        _RUN_CACHE[key] = run
    return run


def parse_avo_result(stdout: str) -> dict:
    """Extrai o objeto que o harness lê do stdout do avaliador.

    O harness pega a ÚLTIMA linha prefixada por `AVO_RESULT:` — um avaliador que
    imprime diagnóstico antes do resultado continua válido. Reproduzir essa
    regra aqui em vez de exigir stdout limpo evita que a suíte seja mais
    exigente que o consumidor real.
    """
    linha = next(
        (ln for ln in reversed(stdout.splitlines()) if ln.strip().startswith("AVO_RESULT:")),
        None,
    )
    if linha is None:
        raise AssertionError(
            "o avaliador não emitiu nenhuma linha AVO_RESULT: no stdout.\n"
            f"últimas linhas:\n{stdout[-2000:]}"
        )
    return json.loads(linha.split("AVO_RESULT:", 1)[1])


def copy_seed(target: Path, destino: Path) -> Path:
    """Copia `seed/` para um diretório de trabalho, como o harness faz no passo 0.

    `__pycache__` fica de fora: bytecode de outro caminho não é o `x_0` e já
    causou confusão ao aparecer no diff do primeiro passo.
    """
    destino.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        target / "seed",
        destino,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    return destino


# ------------------------------------------------------------------- dados


def dataset_status(target: Path) -> tuple[str, str]:
    """Classifica o estado dos dados do alvo em `(estado, detalhe)`.

    Estados: `ok`, `sem_lock`, `nao_gerado`, `corrompido`. A distinção entre os
    dois últimos é o motivo desta função existir — um pula, o outro falha.
    """
    from labkit import datakit

    if not datakit.dataset_lock_path(target).is_file():
        return "sem_lock", f"{datakit.LOCK_NAME} não existe em {target}"
    ok, detalhe = datakit.verify_lock(target)
    if ok:
        return "ok", detalhe
    # `verify_lock` diz "ausente (rode `make data`)" para arquivo que não existe
    # e "checksum divergente" para arquivo alterado. Só o primeiro é esperado
    # numa máquina limpa.
    if "ausente" in detalhe and "divergente" not in detalhe:
        return "nao_gerado", detalhe
    return "corrompido", detalhe


def require_dataset(target: Path) -> None:
    """Pula o teste com instrução acionável quando os dados não foram gerados."""
    estado, detalhe = dataset_status(target)
    if estado == "nao_gerado":
        pytest.skip(
            f"{target.name}: dataset não gerado ({detalhe}). "
            f"Rode `python3 targets/{target.name}/make_data.py` e repita."
        )
    if estado == "sem_lock":
        pytest.skip(f"{target.name}: {detalhe}; test_target_contract cobre a ausência do lock.")


# ----------------------------------------------------------------- fixtures


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """A raiz do repositório, resolvida a partir deste arquivo."""
    return ROOT


@pytest.fixture(scope="session")
def targets() -> list[Path]:
    """Todos os alvos descobertos, em ordem estável."""
    return list(TARGETS)


@pytest.fixture(scope="session")
def eval_runner():
    """Helper: `eval_runner(target, *args) -> (exit, stdout, stderr)`.

    Devolve um `EvalRun`, que desempacota como a tripla pedida e ainda carrega
    `.dump()` para a mensagem de falha.
    """
    return run_eval


@pytest.fixture(scope="session")
def avo_result():
    """Helper: `avo_result(stdout) -> dict` com o payload que o harness lê."""
    return parse_avo_result


@pytest.fixture(scope="session")
def avo_target_loader():
    """`Target.load` do harness upstream, ou um skip com o motivo exato.

    O harness é a autoridade sobre o que um `target.yaml` válido é. Reimplementar
    a validação aqui criaria uma segunda definição de "válido" que envelheceria
    em silêncio — melhor pular quando ele não está disponível e dizer como
    instalá-lo.
    """
    try:
        from avo.config import Target  # noqa: PLC0415
    except ImportError:
        if VENDOR_SRC.is_dir():
            sys.path.insert(0, str(VENDOR_SRC))
        try:
            from avo.config import Target  # noqa: PLC0415
        except ImportError as exc:
            pytest.skip(
                "harness `avo` indisponível "
                f"({exc}); instale com `pip install -e vendor/avo` "
                f"ou garanta que {VENDOR_SRC} existe."
            )
    return Target
