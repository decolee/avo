"""Runner do controle honesto — `full` contra `greedy`.

A ablação de componentes (`runner.py`) responde "qual peça do AVO contribui".
Esta responde a pergunta que vem antes: **a estrutura contribui alguma coisa?**
Se o mesmo modelo, com o mesmo seed, a mesma KB e o mesmo `f` na mão, chega ao
mesmo lugar sozinho, então a arquitetura é overhead e a ablação de componentes
está medindo variação de uma coisa que não faz diferença.

Dois braços de controle, e a diferença entre eles é só a instrução de parada:

  greedy_nat   o comportamento default. A calibração mostrou que ele para
               sozinho em ~12 min e ~US$4, contra ~44 min e ~US$12 do `full`.
               É o que um engenheiro obtém ao pedir "otimize isso".

  greedy_bud   mesma sessão única, mas instruído a gastar o orçamento inteiro e
               a guardar a melhor versão medida. O orçamento é igualado ao
               tempo de agente que o `full` consome nos três passos, para que
               "o `full` ganhou" nunca possa ser respondido com "o `full` teve
               quatro vezes mais compute".

O `full` já foi medido por `runner.py` e vive em `resultados/results.jsonl`;
este runner escreve em `resultados/greedy.jsonl` com as mesmas colunas, para a
análise poder empilhar os dois sem tradução.

Este runner também roda sementes NOVAS do `full`, intercaladas com as do
`greedy` na mesma janela. Os quatro `full` que já existem foram medidos num
outro dia, e comparar contra eles sozinhos deixa "a máquina estava diferente"
como explicação alternativa de qualquer diferença. Sementes contemporâneas
fecham essa porta — e, de quebra, dizem se a própria máquina derivou.

Sequencial por desenho. O `f` deste alvo é vazão medida em wall-clock: dois
agentes rodando ao mesmo tempo disputam CPU e contaminam exatamente o número
que o experimento compara.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import greedy as G  # noqa: E402
import runner as R  # noqa: E402
from runner import _entrypoint, _estado, _sh  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent.parent
AQUI = Path(__file__).resolve().parent

#: Os braços, e por que são estes.
#:
#: O smoke test do plumbing revelou o problema com uma comparação de ponto
#: único: **100 segundos de greedy já chegaram a 3.90x**, contra 4.91x do `full`
#: com 2470s. A curva de ganho contra compute é quase plana nessa faixa, e um
#: experimento que compara só o ponto final compara a parte plana — qualquer
#: diferença some no ruído e a conclusão vira "empate" por falta de resolução,
#: não por ausência de efeito.
#:
#: Então o experimento mede a CURVA. O `full` já tem a dele de graça: cada
#: semente registra o score depois de cada passo, com o tempo de agente
#: acumulado. Do lado do `greedy`, cada ponto é uma sessão nova com orçamento
#: declarado — não um retrato de uma sessão longa, porque um agente que sabe que
#: tem 10 minutos planeja diferente de um que sabe que tem 40, e é o
#: comportamento sob orçamento que se compara ao `full` sob k passos.
#:
#: `orcamento_s=None` quer dizer "o tempo médio de agente que o `full` gasta numa
#: semente", calculado do próprio `results.jsonl` — o pareamento acompanha o dado
#: em vez de um número escrito na mão que envelhece.
BRACOS_GREEDY = {
    # O comportamento default: teto igual ao do `full`, mas livre para parar.
    # A calibração diz que ele para sozinho perto dos 700s. Isso é resultado,
    # não desperdício de orçamento.
    "greedy_nat": {"perfil": "natural", "orcamento_s": None},
    # A curva, com orçamento fechado e instrução de gastar o orçamento inteiro.
    "greedy_b100": {"perfil": "persistente", "orcamento_s": 100.0},
    "greedy_b600": {"perfil": "persistente", "orcamento_s": 600.0},
    "greedy_b1200": {"perfil": "persistente", "orcamento_s": 1200.0},
    "greedy_bmax": {"perfil": "persistente", "orcamento_s": None},
    # O esteio. A rodada 0 mostrou que a instrucao de persistir nao segura o
    # agente: com 2471s de orcamento ele parou aos 731s, com 600s parou aos 405s.
    # Sem um braco que realmente gaste o orcamento, "o `full` ganhou" continuaria
    # tendo como resposta "o `full` teve tres vezes mais compute". Este gasta: a
    # MESMA conversa e retomada mecanicamente ate o orcamento acabar.
    "greedy_cont": {"perfil": "persistente", "orcamento_s": None, "continuo": True},
    # Sementes novas do `full`, para a comparação não depender de dados de outro
    # dia. Delegam ao `runner.py`: é o mesmo braço, não um braço parecido.
    "full": {"perfil": None, "orcamento_s": None},
}

#: O `full` novo tem que ser o MESMO `full` de ontem, ou as sementes não se
#: somam. Estes dois números vêm de `runner.py --passos 3 --timeout-agente 20m`,
#: que foi como as sementes 0–3 rodaram.
PASSOS_FULL = 3
TIMEOUT_FULL = "20m"

#: Onde cada braço escreve. O `full` vai para o arquivo do `runner.py` porque é
#: literalmente o mesmo braço, com o mesmo esquema de linha — sementes novas do
#: mesmo experimento, não um experimento novo.
ARQUIVO = dict.fromkeys(BRACOS_GREEDY, "greedy.jsonl") | {"full": "results.jsonl"}

#: Quantas sementes cada braço leva. O `greedy_nat` leva mais porque é o mais
#: barato e responde a pergunta que um leitor faz primeiro; o `full` leva menos
#: porque já tem quatro sementes medidas.
SEMENTES = {
    "greedy_nat": 5,
    "greedy_b100": 4,
    "greedy_b600": 4,
    # Um ponto so: com a retomada desligada, 1200s e 2471s de orcamento produzem
    # a mesma sessao de ~700s. Gastar quatro sementes nos dois seria comprar o
    # mesmo ponto duas vezes; o orcamento vai para o `greedy_cont`, que e o que
    # a rodada 0 mostrou estar faltando.
    "greedy_b1200": 1,
    "greedy_bmax": 3,
    "greedy_cont": 4,
    "full": 3,
}

#: O `full` já usou as sementes 0–3; as novas continuam a numeração.
PRIMEIRA_SEMENTE = {"full": 4}


def tempo_de_agente_do_full(resultados: Path) -> float:
    """Segundos de agente que o braço `full` consome numa semente, em média.

    É o número que iguala o compute dos dois lados. Soma `dur_agente_s` de todos
    os passos de cada semente do `full` e tira a média entre sementes.
    """
    if not resultados.is_file():
        return 2700.0
    totais = []
    for linha in resultados.read_text(encoding="utf-8").splitlines():
        if not linha.strip():
            continue
        d = json.loads(linha)
        if d.get("braco") != "full":
            continue
        soma = sum(float(p.get("dur_agente_s") or 0.0) for p in (d.get("passos") or []))
        if soma > 0:
            totais.append(soma)
    return sum(totais) / len(totais) if totais else 2700.0


def _cria_run(alvo: str, runs_dir: Path) -> tuple[Path | None, str]:
    """Cria a árvore de trabalho pelo mesmo caminho que o `full` usa.

    `--max-steps 0` monta `work/` a partir do seed, copia a KB, escreve o
    `avo-eval` e — o que interessa aqui — mede e registra o score do seed em
    `scores.jsonl`. Ler o baseline dali em vez de medi-lo à parte mantém os dois
    braços com o mesmo `primary_seed`, medido pelo mesmo código, no mesmo
    instante da máquina.
    """
    runs_dir.mkdir(parents=True, exist_ok=True)
    code, texto = _sh(
        [
            sys.executable,
            "-m",
            "avo",
            "run",
            "--target",
            alvo,
            "--runs-dir",
            str(runs_dir),
            "--max-steps",
            "0",
            "--backend",
            "claude_cli",
            "--permission-mode",
            "acceptEdits",
        ],
        900,
    )
    candidatos = sorted(runs_dir.iterdir())
    if not candidatos:
        return None, f"run nao criado (exit {code}): {texto[-400:]}"
    return candidatos[-1], ""


def _codigo_mudou(run_dir: Path, alvo: str, entrypoint: str) -> bool:
    """O candidato final difere do seed?

    O `full` tem lineage e git para responder isso; o `greedy` não tem nem um
    nem outro, então a comparação é direta contra `seed/`. A coluna existe pelo
    mesmo motivo dos dois lados: uma sessão que falhou e não escreveu nada pode
    medir acima do seed por ruído, e sem esta coluna isso vira "ganho".
    """
    atual = run_dir / "work" / entrypoint
    origem = RAIZ / "targets" / alvo / "seed" / entrypoint
    if not atual.is_file() or not origem.is_file():
        return False
    return atual.read_bytes() != origem.read_bytes()


def roda_um(
    braco: str,
    semente: int,
    alvo: str,
    saida: Path,
    effort: str,
    orcamento_s: float,
) -> dict:
    cfg = BRACOS_GREEDY[braco]
    if braco == "full":
        return R.roda_um("full", semente, alvo, PASSOS_FULL, TIMEOUT_FULL, saida, effort=effort)
    run_dir, erro = _cria_run(alvo, saida / "runs" / f"{braco}-s{semente}")
    if run_dir is None:
        return {"braco": braco, "semente": semente, "alvo": alvo, "erro": erro}

    entrypoint = _entrypoint(alvo)
    inicial = _estado(run_dir)

    t0 = time.time()
    meta = G.roda_greedy(
        alvo,
        run_dir,
        timeout_s=orcamento_s,
        effort=effort,
        log=saida / "logs" / f"{braco}-s{semente}.jsonl",
        perfil=str(cfg["perfil"]),
        continuo=bool(cfg.get("continuo")),
    )
    wall_agente = time.time() - t0

    payload = G.avalia(alvo, run_dir / "work")
    final = G.primary(payload)
    base = inicial["primary"] or 1e-9

    return {
        "braco": braco,
        "semente": semente,
        "alvo": alvo,
        "run_dir": str(run_dir),
        "primary_seed": inicial["primary"],
        "primary_final": final,
        "melhoria_relativa": final / base,
        "correct": bool(payload.get("correct")),
        "erro_avaliador": payload.get("error"),
        "codigo_mudou": _codigo_mudou(run_dir, alvo, entrypoint),
        "perfil": cfg["perfil"],
        "continuo": bool(cfg.get("continuo")),
        "segmentos": len(meta.get("segmentos") or []),
        "orcamento_s": orcamento_s,
        # Mesmas colunas que o `full` grava por passo, para a análise empilhar
        # os dois braços sem caso especial. Uma sessao do greedy = um "passo".
        "passos": [
            {
                "passo": 1,
                "primary_antes": inicial["primary"],
                "primary_depois": final,
                "wall_s": round(wall_agente, 1),
                "custo_usd": meta.get("total_cost_usd"),
                "turnos": meta.get("num_turns"),
                "dur_agente_s": meta.get("duration_s"),
                "morto_por_tempo": bool(meta.get("morto_por_tempo")),
                "agente_ok": bool(meta.get("ok")),
                "erro_agente": None if meta.get("ok") else "is_error ou timeout",
            }
        ],
    }


def _feitos(caminho: Path) -> set[tuple[str, int]]:
    saida: set[tuple[str, int]] = set()
    if caminho.is_file():
        for linha in caminho.read_text(encoding="utf-8").splitlines():
            if linha.strip():
                d = json.loads(linha)
                saida.add((d.get("braco"), d.get("semente")))
    return saida


def fila(rodadas_max: int) -> list[list[tuple[str, int]]]:
    """A ordem de execução: rodadas intercaladas, cada uma sorteada.

    Rodada 0 leva uma semente de TODOS os braços, de propósito. Este laboratório
    já perdeu uma corrida inteira para um restart de container; se isso se
    repetir, o que sobra tem que ser n=1 em toda a curva — de onde já se lê a
    forma — e não n=4 num ponto só, de onde não se lê nada.
    """
    saida = []
    for rodada in range(rodadas_max):
        trabalhos = [
            (braco, PRIMEIRA_SEMENTE.get(braco, 0) + rodada)
            for braco, n in SEMENTES.items()
            if rodada < n
        ]
        random.Random(2000 + rodada).shuffle(trabalhos)
        saida.append(trabalhos)
    return saida


def _feitos(caminho: Path) -> set[tuple[str, int]]:
    saida: set[tuple[str, int]] = set()
    if caminho.is_file():
        for linha in caminho.read_text(encoding="utf-8").splitlines():
            if linha.strip():
                d = json.loads(linha)
                saida.add((d.get("braco"), d.get("semente")))
    return saida


def main() -> int:
    p = argparse.ArgumentParser(description="Controle honesto: full contra greedy")
    p.add_argument("--alvo", default="csv_normalize")
    p.add_argument("--rodadas", type=int, default=max(SEMENTES.values()))
    p.add_argument("--effort", default="medium", help="igual ao do `full`, por desenho")
    p.add_argument("--saida", default=str(AQUI / "resultados"))
    p.add_argument("--plano", action="store_true", help="só imprime a fila e o custo estimado")
    args = p.parse_args()

    saida = Path(args.saida)
    saida.mkdir(parents=True, exist_ok=True)

    pareado = tempo_de_agente_do_full(saida / "results.jsonl")
    print(f"orcamento pareado ao `full`: {pareado:.0f}s de agente por semente", flush=True)

    if args.plano:
        segundos = 0.0
        for rodada, trabalhos in enumerate(fila(args.rodadas)):
            print(f"rodada {rodada}: " + " ".join(f"{b}/s{sm}" for b, sm in trabalhos))
            for braco, _ in trabalhos:
                segundos += float(BRACOS_GREEDY[braco]["orcamento_s"] or pareado)
        print(f"\nteto de tempo de agente: {segundos / 3600:.1f}h (o natural para antes)")
        return 0

    feitos = {nome: _feitos(saida / nome) for nome in set(ARQUIVO.values())}

    for rodada, trabalhos in enumerate(fila(args.rodadas)):
        print(
            f"\n=== rodada {rodada} — ordem: "
            + " ".join(f"{b}/s{sm}" for b, sm in trabalhos)
            + " ===",
            flush=True,
        )
        for braco, semente in trabalhos:
            arquivo = saida / ARQUIVO[braco]
            if (braco, semente) in feitos[ARQUIVO[braco]]:
                print(f"  {braco} s{semente}: já feito, pulando", flush=True)
                continue
            orcamento = BRACOS_GREEDY[braco]["orcamento_s"] or pareado
            t0 = time.time()
            print(f"  {braco} s{semente}: rodando (até {orcamento:.0f}s)...", flush=True)
            reg = roda_um(braco, semente, args.alvo, saida, args.effort, float(orcamento))
            reg["rodada"] = rodada
            reg.setdefault("braco", braco)
            with arquivo.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(reg, ensure_ascii=False) + "\n")
            passos = reg.get("passos") or [{}]
            custo = sum(float(x.get("custo_usd") or 0.0) for x in passos)
            turnos = sum(int(x.get("turnos") or 0) for x in passos)
            print(
                f"  {braco} s{semente}: seed={reg.get('primary_seed', 0):.3f} "
                f"final={reg.get('primary_final', 0):.3f} "
                f"({reg.get('melhoria_relativa', 0):.2f}x) "
                f"US${custo:.2f} {turnos} turnos em {time.time() - t0:.0f}s",
                flush=True,
            )
            # Commit por semente: um restart de container já custou uma corrida
            # inteira deste laboratório uma vez. Resultado que não está no git
            # não existe.
            # `parcial.jsonl` junto: o braço `full` grava ali o registro POR
            # PASSO, e ele é o único lugar onde o passo intermediário sobrevive
            # — a curva de custo × ganho é feita dele. Deixá-lo fora do commit
            # deixava a árvore suja depois de toda semente do `full`.
            subprocess.run(
                ["git", "add", str(arquivo), str(saida / "parcial.jsonl")],
                cwd=str(RAIZ),
                check=False,
                capture_output=True,
            )
            subprocess.run(
                [
                    "git",
                    "commit",
                    "-q",
                    "--no-verify",
                    "-m",
                    f"controle: {braco} s{semente} "
                    f"({reg.get('melhoria_relativa', 0):.2f}x, US${custo:.2f})",
                ],
                cwd=str(RAIZ),
                check=False,
                capture_output=True,
            )
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    raise SystemExit(main())
