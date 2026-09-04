"""Re-medição pareada: elimina a deriva de máquina da razão de ganho.

O ganho é `final / seed`, e os dois são medidos em momentos diferentes — o seed
quando o run é criado, o final até 2,4 h depois. Se a máquina acelera nesse
intervalo, a razão infla; se desacelera, encolhe. Não é hipótese:

    greedy (11 runs)   seeds 2,14 a 2,25   — todos medidos num bloco de 5 h
    full   (9 runs)    seeds 1,59 a 2,41   — medidos ao longo de dois dias

E as quatro sementes do `full` com seed ~28% abaixo da mediana produziram os
quatro maiores ganhos do braço. Com baselines comparáveis o `full` mede 4,64 e
o `greedy` 4,72 — a ordem inverte.

**O conserto.** Para cada run, medir o seed e o artefato final de novo, um atrás
do outro, na mesma máquina, agora. A razão passa a ser entre duas medidas
separadas por segundos em vez de por horas, e a deriva cancela de verdade em vez
de cancelar "em primeira ordem".

Isto NÃO roda agente nenhum: só reavalia código que já existe. Custa segundos por
run e não gasta cota. Mas precisa da máquina ociosa — rodar isto com um agente
trabalhando reintroduz exatamente o ruído que ele existe para remover.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
AQUI = Path(__file__).resolve().parent


def avalia(alvo: str, workdir: Path) -> float:
    """Score do que estiver em `workdir`, pelo mesmo eval.py do experimento."""
    out = subprocess.run(
        [sys.executable, f"targets/{alvo}/eval.py", "--workdir", str(workdir)],
        cwd=str(RAIZ),
        capture_output=True,
        text=True,
        timeout=1800,
        check=False,
    ).stdout
    linha = next(
        (x for x in reversed(out.splitlines()) if x.strip().startswith("AVO_RESULT:")), None
    )
    if not linha:
        return 0.0
    payload = json.loads(linha.split("AVO_RESULT:", 1)[1])
    if not payload.get("correct"):
        return 0.0
    import math

    vals = [v for v in (payload.get("metrics") or {}).values() if v > 0]
    return math.exp(sum(math.log(v) for v in vals) / len(vals)) if vals else 0.0


def par(alvo: str, work: Path) -> tuple[float, float]:
    """Mede o seed e o candidato em sequência imediata, na mesma máquina.

    A ordem importa menos que a proximidade: o que se quer é que as duas medidas
    vejam a mesma máquina. Mede-se seed, candidato, e de novo o seed; o baseline
    usado é a média dos dois, o que absorve deriva monotônica durante a propria
    re-medição.
    """
    semente_dir = RAIZ / "targets" / alvo / "seed"
    with tempfile.TemporaryDirectory(prefix="remedir-") as tmp:
        espelho = Path(tmp) / "seed"
        shutil.copytree(semente_dir, espelho)
        s1 = avalia(alvo, espelho)
        cand = avalia(alvo, work)
        s2 = avalia(alvo, espelho)
    return (s1 + s2) / 2.0, cand


def main() -> int:
    p = argparse.ArgumentParser(description="Re-medicao pareada dos artefatos finais")
    p.add_argument("--alvo", default="sql_agg")
    p.add_argument("--saida", default=str(AQUI / "resultados" / "fase2_sql_agg"))
    p.add_argument("--out", default=None)
    args = p.parse_args()

    base = Path(args.saida)
    destino = Path(args.out or (base / "remedido.jsonl"))

    linhas = []
    for arquivo in ("results.jsonl", "greedy.jsonl"):
        caminho = base / arquivo
        if not caminho.is_file():
            continue
        for x in caminho.read_text(encoding="utf-8").splitlines():
            if x.strip():
                linhas.append(json.loads(x))

    feitos = set()
    if destino.is_file():
        for x in destino.read_text(encoding="utf-8").splitlines():
            if x.strip():
                d = json.loads(x)
                feitos.add((d["braco"], d["semente"]))

    print(
        f"{'braco':>12} {'s':>3} {'seed_orig':>10} {'seed_novo':>10} {'ganho_orig':>11} {'ganho_novo':>11}"
    )
    for d in linhas:
        chave = (d["braco"], d["semente"])
        if chave in feitos:
            continue
        work = Path(d["run_dir"]) / "work"
        if not work.is_dir():
            print(f"{d['braco']:>12} {d['semente']:>3}  arvore ausente, pulando")
            continue
        t0 = time.time()
        seed_novo, cand_novo = par(args.alvo, work)
        ganho_novo = cand_novo / seed_novo if seed_novo else 0.0
        registro = {
            "braco": d["braco"],
            "semente": d["semente"],
            "seed_original": d["primary_seed"],
            "final_original": d["primary_final"],
            "ganho_original": d["melhoria_relativa"],
            "seed_remedido": seed_novo,
            "final_remedido": cand_novo,
            "ganho_remedido": ganho_novo,
            "medido_em": time.time(),
            "duracao_s": round(time.time() - t0, 1),
        }
        with destino.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(registro, ensure_ascii=False) + "\n")
        print(
            f"{d['braco']:>12} {d['semente']:>3} {d['primary_seed']:>10.3f} "
            f"{seed_novo:>10.3f} {d['melhoria_relativa']:>10.2f}x {ganho_novo:>10.2f}x"
        )
    print(f"\n-> {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
