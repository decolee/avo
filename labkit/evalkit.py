"""A mecânica de `f`: medir, julgar, emitir.

O harness lê **um** objeto JSON do stdout do avaliador, prefixado por
`AVO_RESULT:` (contrato em `vendor/avo/docs/TARGETS.md`)::

    {"correct": bool, "metrics": {...}, "error": str|null, "notes": str}

`primary` — o escalar que a busca maximiza — é a média geométrica de `metrics`
quando o avaliador não manda um explícito, e é **zerado** quando `correct` é
falso. Isso é o gate de correção do paper (§3.1): candidato errado não vale
"um pouco menos", vale zero.

Três decisões deste laboratório, todas com motivo:

*Regimes são formas de dado, não repetições do mesmo dado.* Medir o mesmo
benchmark três vezes e chamar de três métricas não diagnostica nada: as três
sobem juntas. Regimes diferentes (muitos grupos / poucos grupos / distribuição
enviesada) mostram *onde* a mudança ajudou, e a média geométrica pune quem
otimiza um regime e regride outro.

*Mediana de repetições, nunca o melhor.* O melhor-de-N recompensa variância —
basta rodar mais vezes para "melhorar". A mediana é estável e honesta.

*O custo da avaliação é parte do design.* `Measurement` carrega o tempo de
parede real e `budget_report` o compara com a faixa saudável, porque um seed que
leva 90 s por execução custa 8 min por passo e inviabiliza qualquer busca longa.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import os
import statistics
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

AVO_RESULT = "AVO_RESULT:"

#: Teto para o custo de UMA avaliação completa do SEED, em segundos. Acima
#: disso cada passo do agente vira espera: o paper explorou 500+ direções, e a
#: 140 s por avaliação isso são 19 horas só de medição. A regra saiu da Falha 2
#: e vale para o SEED, não para o candidato otimizado — dimensionar pelo
#: otimizado foi exatamente o erro cometido.
BUDGET_CEILING_S = 25.0

#: Piso para a duração de UMA execução medida, em segundos. É uma escala
#: diferente do teto e mede outra coisa: o teto protege o tempo do agente, o
#: piso protege o sinal. Abaixo de ~20 ms a variação do relógio e do escalonador
#: fica comparável à melhoria que se quer detectar, e a busca passa a perseguir
#: ruído. Note que o piso vale para o candidato mais RÁPIDO imaginável, não para
#: o seed: é ele que chega perto do chão.
RUN_FLOOR_S = 0.020


# --------------------------------------------------------------------- saída


def emit(payload: dict[str, Any]) -> None:
    """Imprime o resultado no formato que o harness lê."""
    print(AVO_RESULT + " " + json.dumps(payload, ensure_ascii=False))
    sys.stdout.flush()


def emit_failure(error: str, notes: str = "") -> None:
    """Emite uma reprovação. `error` é lido pelo agente: seja diagnóstico."""
    emit({"correct": False, "metrics": {}, "error": error, "notes": notes})


def emit_success(metrics: dict[str, float], notes: str = "") -> None:
    emit({"correct": True, "metrics": metrics, "error": None, "notes": notes})


def emit_baselines(baselines: dict[str, dict[str, float]]) -> None:
    """Baselines são medidas uma vez e mostradas ao agente como alvo real.

    As chaves de métrica de cada baseline devem ser **as mesmas** dos regimes do
    candidato; senão o número aparece na UI sem nada com que ser comparado.
    """
    emit({"baselines": baselines})


# ------------------------------------------------------------------ medição


@dataclass
class Regime:
    """Uma configuração do benchmark: um jeito diferente de estressar o código.

    `args_factory`, quando presente, é chamado **antes de cada execução medida**
    e substitui `args`. Existe por um motivo específico: um candidato que
    memoiza a saída indexada pelo caminho do arquivo devolve o resultado certo
    instantaneamente a partir da segunda chamada, passa no gate, e marca um
    score milhares de vezes maior sem ter otimizado nada. Entregar um caminho
    novo a cada execução faz o cache errar. Veja `unique_alias`.
    """

    name: str
    args: tuple[Any, ...] = ()
    description: str = ""
    args_factory: Callable[[], tuple[Any, ...]] | None = None

    def call_args(self) -> tuple[Any, ...]:
        return self.args_factory() if self.args_factory is not None else self.args


@dataclass
class Measurement:
    """O que uma medição produziu, incluindo o quanto ela custou."""

    per_regime: dict[str, float] = field(default_factory=dict)  # segundos (mediana)
    raw: dict[str, list[float]] = field(default_factory=dict)
    wall_s: float = 0.0

    def throughput(self) -> dict[str, float]:
        """Métricas em execuções/segundo — direção `maximize`."""
        return {name: round(1.0 / secs, 6) for name, secs in self.per_regime.items() if secs > 0}

    def spread(self) -> dict[str, float]:
        """Coeficiente de variação por regime: quanto do sinal é ruído."""
        out = {}
        for name, runs in self.raw.items():
            if len(runs) > 1 and statistics.fmean(runs) > 0:
                out[name] = round(statistics.pstdev(runs) / statistics.fmean(runs), 4)
        return out

    def notes(self) -> str:
        cv = self.spread()
        parts = [
            f"{name}={secs * 1000:.1f}ms" + (f"±{cv[name] * 100:.1f}%" if name in cv else "")
            for name, secs in sorted(self.per_regime.items())
        ]
        return f"medianas: {', '.join(parts)}; avaliação levou {self.wall_s:.1f}s"


def measure(
    fn: Callable[..., Any],
    regimes: Sequence[Regime],
    repeats: int = 5,
    warmup: int = 1,
    fn_factory: Callable[[], Callable[..., Any]] | None = None,
) -> Measurement:
    """Roda `fn` em cada regime e devolve a mediana dos tempos.

    `warmup` descarta as primeiras execuções: a primeira paga cache de página do
    arquivo e aquecimento de import, e essa constante não é propriedade do
    candidato. Descartá-la explicitamente é mais honesto do que reportar um
    regime "cold" que na prática mede o sistema de arquivos.

    `fn_factory`, quando presente, é chamado antes de **cada** execução e produz
    um callable novo — na prática, reimportar o módulo do candidato. É a defesa
    geral contra memoização: nenhum estado de módulo sobrevive de uma execução
    para a outra, então cache indexado por caminho, por conteúdo, ou por
    qualquer outra coisa erra sempre. Sem isso, um candidato que memoiza a saída
    passa no gate (o resultado *está* correto) e marca um score ordens de
    grandeza maior sem ter otimizado nada.

    O custo é que trabalho feito no import — compilar uma regex, montar uma
    tabela — passa a ser cobrado em toda execução. Isso é intencional e justo:
    uma constante de microssegundos não muda o ranking, e um candidato que faz
    algo caro no import está movendo trabalho para fora da medição.
    """
    result = Measurement()
    started = time.perf_counter()
    for regime in regimes:
        for _ in range(max(0, warmup)):
            (fn_factory() if fn_factory else fn)(*regime.call_args())
        runs: list[float] = []
        for _ in range(max(1, repeats)):
            call = fn_factory() if fn_factory else fn
            args = regime.call_args()
            tick = time.perf_counter()
            call(*args)
            runs.append(time.perf_counter() - tick)
        result.raw[regime.name] = runs
        result.per_regime[regime.name] = statistics.median(runs)
    result.wall_s = time.perf_counter() - started
    return result


# ------------------------------------------------------- defesa contra trapaça

#: Fração do custo de simplesmente ler os bytes de entrada abaixo da qual uma
#: execução é considerada impossível. Nenhuma implementação honesta pode ser
#: muito mais rápida que ler o próprio arquivo que ela precisa processar; quem
#: consegue não está processando — está devolvendo resultado memoizado.
#: A margem é generosa (metade do piso físico) porque leitura tem variância e
#: reprovar candidato honesto é tão danoso quanto aprovar trapaça.
PLAUSIBILITY_RATIO = 0.5


#: Eventos de auditoria que abrem arquivo por dentro do C ou saem do processo, e
#: que por isso nunca apareceriam num `open` do lado Python. Bloquear pelo evento
#: fecha a familia inteira de uma vez: `os.popen` importa `subprocess` por
#: dentro (invisivel para uma checagem de AST), e `sqlite3.connect` abre o
#: arquivo no C. Uma auditoria adversarial derrubou a versao anterior desta
#: guarda — que so remendava `builtins.open`/`io.open`/`os.open` — com
#: candidatos usando exatamente esses caminhos.
_EVENTOS_NEGADOS = (
    "os.system",
    "os.exec",
    "os.spawn",
    "os.posix_spawn",
    "os.startfile",
    "sqlite3.connect",
    "shutil.copyfile",
    "shutil.move",
)


def _montar_guarda():
    """Fecha a guarda sobre celulas, nao sobre globais do modulo.

    `sys.addaudithook` nao pode ser removido: uma vez instalado, fica. Por isso
    a guarda liga e desliga por um contador, e esse contador **nao** pode viver
    numa global do modulo — seria um interruptor com etiqueta, e uma linha do
    tipo `evalkit._PROFUNDIDADE = 0` desligaria a defesa inteira. Numa celula de
    fecho o mesmo ataque nao tem o que atribuir.
    """
    profundidade = [0]
    instalado = [False]
    registro: list[list[str]] = []

    def _negar(descricao: str, mensagem: str) -> None:
        if registro:
            registro[-1].append(descricao)
        raise PermissionError(mensagem)

    def auditor(evento: str, args) -> None:
        if profundidade[0] <= 0:
            return
        if evento == "open":
            caminho, modo, flags = (list(args) + [None, None, None])[:3]
            try:
                resolvido = os.path.realpath(os.fspath(caminho))
            except (TypeError, ValueError):
                return
            if resolvido.endswith(".pyc") or f"{os.sep}__pycache__{os.sep}" in resolvido:
                return
            escrita = False
            if isinstance(modo, str):
                escrita = any(c in modo for c in ("w", "a", "x", "+"))
            elif isinstance(flags, int):
                escrita = bool(
                    flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC)
                )
            if escrita:
                _negar(
                    f"escreveu em {resolvido}",
                    "o candidato nao pode escrever em disco durante a medicao: um cache "
                    "em disco devolve trabalho ja pago de graca, sem que nada tenha "
                    "ficado mais rapido",
                )
            return
        if evento in _EVENTOS_NEGADOS or evento.startswith("subprocess."):
            _negar(
                f"disparou {evento}",
                f"o candidato nao pode usar {evento} durante a medicao: e uma porta de "
                "arquivo ou de processo que escapa da medicao",
            )

    @contextlib.contextmanager
    def no_disk_writes(violations: list[str]):
        """Proibe escrita em disco enquanto o candidato roda. Terceira camada.

        As duas primeiras defesas — caminho novo e modulo novo por execucao —
        matam qualquer memoizacao **em processo**. Sobrava um caminho: gravar o
        resultado num arquivo indexado pelo conteudo da entrada e le-lo nas
        execucoes seguintes. Um cache em disco atravessa o `fn_factory` intacto,
        porque nao e estado de modulo, e devolve trabalho ja pago de graca.

        A guarda e um gancho de auditoria (`sys.addaudithook`), nao um remendo em
        `builtins.open`. A diferenca importa: quem dispara o evento e o proprio
        interpretador, no ponto em que o arquivo e aberto, entao `io.FileIO`,
        `os.popen` e `sqlite3.connect` caem na mesma rede. A versao remendada
        desta guarda foi derrubada por uma auditoria adversarial usando
        exatamente esses tres caminhos.

        Duas sutilezas que valem manter:

        - A violacao e **anotada antes** de a excecao subir. Um candidato que
          embrulhe a operacao em `try/except` nao apaga o registro; so deixa de
          saber que falhou.
        - `.pyc` e `__pycache__` sao liberados. Um `import` tardio dentro da
          funcao medida grava bytecode, e reprovar por isso seria reprovar
          candidato honesto.

        Leitura continua livre: nos alvos de throughput, ler o arquivo de entrada
        e exatamente o trabalho. Um alvo que tambem precise restringir leitura —
        como o `dedupe_match`, cujo gabarito mora no disco — adiciona essa regra
        por cima, no seu proprio gate.
        """
        nonlocal instalado
        if not instalado[0]:
            sys.addaudithook(auditor)
            instalado[0] = True
        registro.append(violations)
        profundidade[0] += 1
        try:
            yield
        finally:
            profundidade[0] -= 1
            registro.pop()

    return no_disk_writes


no_disk_writes = _montar_guarda()


def unique_alias(path: str | Path, tmpdir: str | Path) -> str:
    """Um caminho novo, apontando para o mesmo conteúdo, a cada chamada.

    Symlink em vez de cópia: custa microssegundos e não duplica dezenas de MB
    nem perturba o cache de página. O objetivo é só que a string do caminho seja
    diferente, para que um cache indexado por caminho não acerte.
    """
    import itertools
    import os

    counter = getattr(unique_alias, "_counter", None)
    if counter is None:
        counter = itertools.count()
        unique_alias._counter = counter  # type: ignore[attr-defined]

    source = Path(path).resolve()
    link = Path(tmpdir) / f"{next(counter):06d}-{source.name}"
    os.symlink(source, link)
    return str(link)


def read_floor(paths: Sequence[str | Path], repeats: int = 3) -> float:
    """Quanto custa só ler os bytes destes arquivos. O piso físico do trabalho.

    Qualquer transformação que consome o arquivo inteiro tem que pagar ao menos
    isto. É um limite inferior honesto e independente de linguagem ou algoritmo.
    """
    runs = []
    for _ in range(max(1, repeats)):
        tick = time.perf_counter()
        for path in paths:
            with open(path, "rb") as fh:
                while fh.read(1 << 20):
                    pass
        runs.append(time.perf_counter() - tick)
    return statistics.median(runs)


def implausible_speed(per_regime: dict[str, float], floors: dict[str, float]) -> tuple[bool, str]:
    """Detecta score obtido sem fazer o trabalho.

    Devolve `(suspeito, detalhe)`. Um candidato que memoiza a saída devolve o
    resultado certo em microssegundos: passa no gate, e marca um score milhares
    de vezes maior sem ter otimizado nada. Como o resultado *está* correto,
    nenhum gate de correção pega isso — só a física pega.
    """
    for name, median in sorted(per_regime.items()):
        floor = floors.get(name)
        if floor is None:
            continue
        limit = floor * PLAUSIBILITY_RATIO
        if median < limit:
            return True, (
                f"regime {name}: {median * 1000:.3f}ms é mais rápido que ler o próprio "
                f"arquivo de entrada ({floor * 1000:.1f}ms). Nenhuma implementação que "
                "processa os dados consegue isso — resultado memoizado ou cacheado entre "
                "chamadas não conta como otimização."
            )
    return False, "velocidade compatível com o custo de ler a entrada"


def budget_report(
    seed_wall_s: float,
    fastest_run_s: float | None = None,
    label: str = "avaliação do seed",
) -> tuple[bool, str]:
    """Diz se o target está dimensionado de forma saudável (Falha 2).

    Duas checagens que medem coisas diferentes e falham por motivos opostos:
    o custo total da avaliação do **seed** não pode estourar o teto (senão a
    busca fica cara), e a execução medida mais rápida não pode ficar abaixo do
    piso (senão a melhoria some no ruído). Passar `fastest_run_s` é opcional
    porque nem todo target consegue estimar seu candidato mais rápido.
    """
    problems = []
    if seed_wall_s > BUDGET_CEILING_S:
        problems.append(
            f"{label} custa {seed_wall_s:.1f}s (> {BUDGET_CEILING_S:.0f}s): cada passo do agente "
            "vira espera. Reduza o dataset — dimensione pelo SEED, não pelo candidato rápido."
        )
    if fastest_run_s is not None and fastest_run_s < RUN_FLOOR_S:
        problems.append(
            f"a execução mais rápida leva {fastest_run_s * 1000:.1f}ms "
            f"(< {RUN_FLOOR_S * 1000:.0f}ms): a melhoria vai afundar no ruído de medição. "
            "Aumente o dataset."
        )
    if problems:
        return False, " | ".join(problems)
    detail = f"{label} custa {seed_wall_s:.1f}s"
    if fastest_run_s is not None:
        detail += f"; execução mais rápida {fastest_run_s * 1000:.0f}ms"
    return True, detail + " — dimensionamento saudável"


# --------------------------------------------------------------------- gate


@dataclass
class Gate:
    """O árbitro de `correct`. Nunca deve ser afrouxado para um candidato passar.

    `judge(fn) -> (ok, detalhe)` é a única coisa que o target precisa fornecer.
    O gate existe separado do benchmark de propósito: o dataset que decide
    correção é pequeno e adversarial, o que mede tempo é grande e comum. Um
    dataset com 2 casas decimais não consegue expor erro de arredondamento
    incremental — a divergência é exatamente zero — e foi assim que a Falha 1
    passou despercebida.
    """

    judge: Callable[[Callable[..., Any]], tuple[bool, str]]
    description: str = ""

    def check(self, fn: Callable[..., Any]) -> tuple[bool, str]:
        try:
            return self.judge(fn)
        except Exception as exc:  # noqa: BLE001 — qualquer erro do candidato é reprovação
            return False, f"{type(exc).__name__}: {exc}"


@dataclass
class MutantSuite:
    """Implementações sabidamente erradas que o gate **tem** que rejeitar.

    Um gate que nunca foi atacado não é um gate, é uma esperança. Cada mutante
    codifica um jeito plausível de estar errado — não um bug absurdo, mas o
    atalho que um otimizador de verdade tentaria.
    """

    reference: Callable[..., Any]
    mutants: list[tuple[str, Callable[..., Any]]] = field(default_factory=list)
    minimum: int = 5

    def run(self, gate: Gate) -> tuple[bool, list[tuple[str, bool, str]]]:
        rows: list[tuple[str, bool, str]] = []
        ok_ref, detail = gate.check(self.reference)
        rows.append(("REFERÊNCIA (deve passar)", ok_ref, detail))
        for name, fn in self.mutants:
            ok, detail = gate.check(fn)
            rows.append((f"mutante {name} (deve falhar)", ok, detail))
        survivors = [name for name, ok, _ in rows[1:] if ok]
        passed = ok_ref and not survivors and len(self.mutants) >= self.minimum
        return passed, rows

    def selftest(self, gate: Gate, stream=sys.stdout) -> bool:
        passed, rows = self.run(gate)
        for name, ok, detail in rows:
            print(f"  {'PASS' if ok else 'FAIL':4}  {name:44} {detail[:70]}", file=stream)
        if len(self.mutants) < self.minimum:
            print(
                f"\n  Só {len(self.mutants)} mutantes; o mínimo do laboratório é {self.minimum}.",
                file=stream,
            )
        print(f"\nGATE SELFTEST: {'OK' if passed else 'GATE FURADO'}", file=stream)
        return passed


# ------------------------------------------------------------------ módulos


def load_module(path: str | Path, name: str = "candidate") -> Any:
    """Importa o candidato a partir do arquivo, sem poluir o sys.path."""
    path = Path(path)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"não consegui carregar {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def standard_parser(description: str) -> argparse.ArgumentParser:
    """A CLI que todo avaliador do laboratório expõe.

    `--selftest` não é opcional: é o que prova que o gate morde, e o CI e o hook
    do Claude Code rodam exatamente este comando.
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--workdir", default=None, help="diretório do candidato (work/)")
    parser.add_argument("--baselines", action="store_true", help="mede as baselines e sai")
    parser.add_argument("--selftest", action="store_true", help="o gate rejeita os mutantes?")
    parser.add_argument("--budget", action="store_true", help="mede o custo do seed e sai")
    return parser


def candidate_path(workdir: str | None, entrypoint: str) -> Path:
    if not workdir:
        raise SystemExit("--workdir é obrigatório (ou use --selftest/--baselines/--budget)")
    return Path(workdir) / entrypoint
