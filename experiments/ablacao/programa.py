"""Orquestrador do programa completo — roda tudo, sozinho, e se levanta sozinho.

Este arquivo existe por dois motivos concretos, os dois aprendidos na marra.

**Um restart mata a corrida.** Um container reiniciado já custou uma corrida
inteira deste laboratório, e a Fase 2A morreu em silêncio cinco minutos depois de
lançada, sem traceback. Cada fase aqui é retomável — os runners pulam
`(braço, semente)` que já está no disco — então relançar é barato e seguro. O
watchdog relança.

**As fases não podem se sobrepor.** O `f` deste laboratório é vazão medida em
wall-clock: dois agentes rodando ao mesmo tempo disputam CPU e contaminam
exatamente o número que o experimento compara. Nada aqui roda em paralelo, nunca,
nem para "aproveitar a máquina ociosa" enquanto um agente pensa.

Ordem, e por quê:

  sondas   15 min. Corrige dados publicados que estão errados: as cinco frações
           de §3e nos `target.yaml` foram medidas com agentes cegos.
  2A       full × greedy_nat, n=11. A pergunta primária.
  2B       greedy_cont pareado por compute. Fecha a porta do "o full teve mais
           relógio", que é a primeira resposta que 2A vai receber se o full ganhar.
  3        ablação de componentes, reusando as sementes do `full` de 2A como
           braço de referência — o que economiza 26h de relógio.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
AQUI = Path(__file__).resolve().parent
SAIDA = AQUI / "resultados" / "fase2_sql_agg"


#: Trava de instancia unica. Sem ela, dois programas rodaram em paralelo por 1,5h
#: — um `pkill -f` com ancora `^` nao casou o processo antigo, e eu presumi que
#: tinha matado. O novo mediu onze sessoes de `greedy_nat` enquanto o antigo
#: rodava passos do `full` na mesma maquina.
#:
#: Isso e a contaminacao que o protocolo inteiro existe para evitar: o `f` deste
#: laboratorio e vazao em wall-clock, e dois agentes disputando CPU medem um
#: numero que nao e o do candidato. Presumir exclusao mutua nao basta; ela tem
#: que ser garantida por algo que nao dependa de eu ter matado o processo certo.
TRAVA = AQUI / "resultados" / ".programa.lock"


def trava_exclusiva():
    """Devolve o descritor travado, ou None se ja houver um programa rodando."""
    TRAVA.parent.mkdir(parents=True, exist_ok=True)
    # O descritor tem que sobreviver a esta funcao: o `flock` vale enquanto ele
    # existir, entao um `with` liberaria a trava justamente ao devolve-la.
    fh = open(TRAVA, "w", encoding="utf-8")  # noqa: SIM115
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    fh.write(f"{os.getpid()}\n{time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    fh.flush()
    return fh


def _linhas(caminho: Path) -> list[dict]:
    if not caminho.is_file():
        return []
    return [json.loads(x) for x in caminho.read_text(encoding="utf-8").splitlines() if x.strip()]


def _feitos(caminho: Path, bracos: set[str]) -> int:
    return sum(1 for d in _linhas(caminho) if d.get("braco") in bracos)


@dataclass
class Fase:
    nome: str
    argv: list[str]
    #: Quantas linhas de resultado a fase precisa produzir para estar completa.
    #: `None` quer dizer que a conclusao e decidida por `marcador` — um arquivo
    #: cuja existencia prova que a fase ja rodou. Sem isso, um reinicio do
    #: programa refazia as sondas toda vez: ~20 min e US$ 3 por reinicio, e
    #: churn nas declaracoes de `sonda_100s_fracao`, que mudam um pouco a cada
    #: medicao e virariam commits sem informacao.
    alvo_linhas: int | None = None
    marcador: Path | None = None
    arquivo: Path | None = None
    bracos: set[str] = field(default_factory=set)
    #: Horas de relógio esperadas. Só informativo, para o log dizer o que falta.
    horas: float = 0.0

    def completa(self) -> bool:
        if self.marcador is not None:
            return self.marcador.is_file()
        if self.alvo_linhas is None or self.arquivo is None:
            return False
        return _feitos(self.arquivo, self.bracos) >= self.alvo_linhas

    def progresso(self) -> str:
        if self.marcador is not None:
            return "feita" if self.marcador.is_file() else "pendente"
        if self.alvo_linhas is None or self.arquivo is None:
            return "—"
        return f"{_feitos(self.arquivo, self.bracos)}/{self.alvo_linhas}"


def constroi_fases(n: int, passos: int, janela: int, alvo: str, n3: int) -> list[Fase]:
    comum = [
        sys.executable,
        str(AQUI / "runner_greedy.py"),
        "--alvo",
        alvo,
        "--n",
        str(n),
        "--passos-full",
        str(passos),
        "--janela-estagnacao",
        str(janela),
        "--orcamento-pareado-s",
        "8627",
        "--saida",
        str(SAIDA),
    ]
    return [
        Fase(
            nome="sondas",
            argv=[sys.executable, str(AQUI / "sondas_todas.py")],
            marcador=AQUI / "resultados" / "sondas_vendo.json",
            horas=0.3,
        ),
        # 2A esta partido em dois por uma razao operacional, nao cientifica, e a
        # razao esta declarada em FASE2_SQL_AGG.md §7. Os containers desta
        # plataforma passaram a viver de 3 a 16 minutos, e um passo do `full`
        # leva ~18: ele nunca fecha. Uma sessao do `greedy_nat` leva 5 a 7
        # minutos e CABE. Rodar primeiro o braco cuja unidade cabe e o que
        # transforma capacidade instavel em dado commitado.
        #
        # O custo e real: a ordem intercalada de §4 do protocolo deixa de valer
        # entre os dois bracos, e deriva de maquina passa a ser um confundidor
        # possivel. A analise mede essa deriva pelos seeds e reporta.
        Fase(
            nome="2A-greedy",
            argv=[*comum, "--bracos", "greedy_nat"],
            alvo_linhas=n,
            arquivo=SAIDA / "greedy.jsonl",
            bracos={"greedy_nat"},
            horas=1.5,
        ),
        Fase(
            nome="2A-full",
            argv=[*comum, "--bracos", "full"],
            alvo_linhas=n,
            arquivo=SAIDA / "results.jsonl",
            bracos={"full"},
            horas=28.0,
        ),
        Fase(
            nome="2B",
            argv=[*comum, "--bracos", "greedy_cont"],
            alvo_linhas=n,
            arquivo=SAIDA / "greedy.jsonl",
            bracos={"greedy_cont"},
            horas=26.0,
        ),
        Fase(
            nome="3",
            argv=[
                sys.executable,
                str(AQUI / "runner.py"),
                "--alvo",
                alvo,
                "--rodadas",
                str(n),
                "--passos",
                str(passos),
                "--janela-estagnacao",
                str(janela),
                "--timeout-agente",
                "20m",
                "--saida",
                str(SAIDA),
                "--bracos",
                "no_supervisor",
                "no_kb",
                "no_memory",
            ],
            alvo_linhas=3 * n3,
            arquivo=SAIDA / "results.jsonl",
            bracos={"no_supervisor", "no_kb", "no_memory"},
            horas=7.2 * n3,
        ),
    ]


def roda_fase(fase: Fase, tentativas: int, log) -> bool:
    for tentativa in range(1, tentativas + 1):
        if fase.completa():
            return True
        log(f"[{fase.nome}] tentativa {tentativa}/{tentativas} — progresso {fase.progresso()}")
        t0 = time.time()
        proc = subprocess.run(fase.argv, cwd=str(RAIZ), check=False)
        dur = time.time() - t0
        log(f"[{fase.nome}] saiu com {proc.returncode} depois de {dur / 3600:.2f}h")
        if fase.alvo_linhas is None:
            return True  # fase sem contador roda uma vez e pronto
        if fase.completa():
            return True
        # Uma fase que morre sem avançar nada duas vezes seguidas nao vai
        # avançar na terceira: e defeito, nao instabilidade.
        if dur < 120 and tentativa >= 2:
            log(f"[{fase.nome}] morreu em {dur:.0f}s duas vezes — desistindo")
            return False
        time.sleep(30)
    return fase.completa()


def main() -> int:
    p = argparse.ArgumentParser(description="Programa completo do sql_agg")
    p.add_argument("--alvo", default="sql_agg")
    p.add_argument("--n", type=int, default=11)
    p.add_argument(
        "--n-fase3",
        type=int,
        default=6,
        help="sementes por braço na ablação de componentes; menor que --n porque "
        "sao tres bracos e o relogio, nao o dinheiro, e o recurso escasso",
    )
    p.add_argument("--passos", type=int, default=8)
    p.add_argument("--janela", type=int, default=2)
    p.add_argument("--tentativas", type=int, default=8, help="relançamentos por fase")
    p.add_argument("--fases", nargs="*", default=None)
    p.add_argument("--plano", action="store_true")
    args = p.parse_args()

    fases = constroi_fases(args.n, args.passos, args.janela, args.alvo, args.n_fase3)
    if args.fases:
        fases = [f for f in fases if f.nome in args.fases]

    def log(msg: str) -> None:
        print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)

    if not args.plano:
        # O `flock` e liberado pelo kernel quando o processo morre, inclusive
        # por SIGKILL ou reciclagem de container — entao ele nunca deixa uma
        # trava orfa impedindo o relancamento.
        fh = trava_exclusiva()
        if fh is None:
            log("outro programa ja esta rodando (trava em resultados/.programa.lock)")
            return 3

    if args.plano:
        total = sum(f.horas for f in fases if not f.completa())
        for f in fases:
            estado = "COMPLETA" if f.completa() else f"{f.progresso()}"
            print(f"  {f.nome:>7}  {estado:>10}  ~{f.horas:.1f}h  {' '.join(f.argv[1:])[:70]}")
        print(f"\n  relogio restante estimado: {total:.0f}h")
        return 0

    for fase in fases:
        if fase.completa():
            log(f"[{fase.nome}] já completa ({fase.progresso()}), pulando")
            continue
        ok = roda_fase(fase, args.tentativas, log)
        log(f"[{fase.nome}] {'COMPLETA' if ok else 'INCOMPLETA'} — {fase.progresso()}")
        if not ok:
            log(f"[{fase.nome}] parando o programa: fase seguinte depende desta")
            return 1
    log("programa completo")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    raise SystemExit(main())
