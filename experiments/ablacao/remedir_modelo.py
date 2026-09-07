"""Re-medição pareada do experimento do eixo do modelo.

Reusa `remedir.par()` — a lógica validada na Fase 2A: mede o seed, o candidato e
o seed de novo, em sequência imediata, e usa a média dos dois seeds como base. A
razão passa a ser entre medidas separadas por segundos em vez de por dias.

**Por que foi preciso aqui.** O experimento pareado por dólar comparou runs de
dias e durações diferentes, e o `primary_seed` — medido uma vez no início de cada
run, sobre um artefato de seed IDÊNTICO — variou de 0,913 a 1,536 entre eles.
1,68× no mesmo artefato. Isso é o defeito 9 reaparecendo: a razão `final/seed`
cancela deriva DENTRO de um run, e é por isso que ela é a métrica certa numa
ablação com braços intercalados. Entre experimentos ela não cancela nada, porque
o numerador e o denominador vêm de máquinas em estados diferentes.

Não roda agente nenhum: só reavalia código que já existe. Mas **precisa da
máquina ociosa** — rodar isto com um agente trabalhando reintroduz o ruído que
ele existe para remover.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import remedir as RM

AQUI = Path(__file__).resolve().parent
RES = AQUI / "resultados"

#: As três fontes, e o rótulo de braço que cada uma recebe na saída.
FONTES = (
    ("opus-8p", RES / "ablacao_sql_workload" / "results.jsonl", lambda d: d.get("braco") == "full"),
    ("sonnet-8p", RES / "piloto_modelo_claude-sonnet-5" / "piloto.jsonl", None),
    ("sonnet-36p", RES / "dolar_sonnet_36p" / "piloto.jsonl", None),
)


def main() -> int:
    p = argparse.ArgumentParser(description="Re-medicao pareada do eixo do modelo")
    p.add_argument("--alvo", default="sql_workload")
    p.add_argument("--out", default=str(RES / "remedido_modelo.jsonl"))
    args = p.parse_args()

    destino = Path(args.out)
    feitos = set()
    if destino.is_file():
        for x in destino.read_text(encoding="utf-8").splitlines():
            if x.strip():
                d = json.loads(x)
                feitos.add((d["braco"], d["semente"]))

    print(
        f"{'braco':>12} {'s':>3} {'seed_orig':>10} {'seed_novo':>10} {'raz_orig':>9} {'raz_nova':>9}"
    )
    for rotulo, caminho, filtro in FONTES:
        if not caminho.is_file():
            print(f"{rotulo:>12}  ausente: {caminho}")
            continue
        for linha in caminho.read_text(encoding="utf-8").splitlines():
            if not linha.strip():
                continue
            d = json.loads(linha)
            if filtro and not filtro(d):
                continue
            if "melhoria_relativa" not in d:
                continue
            chave = (rotulo, d["semente"])
            if chave in feitos:
                continue
            work = Path(d["run_dir"]) / "work"
            if not work.is_dir():
                print(f"{rotulo:>12} {d['semente']:>3}  arvore ausente, pulando")
                continue
            t0 = time.time()
            seed_novo, cand_novo = RM.par(args.alvo, work)
            razao = cand_novo / seed_novo if seed_novo else 0.0
            reg = {
                "braco": rotulo,
                "semente": d["semente"],
                "seed_original": d["primary_seed"],
                "final_original": d["primary_final"],
                "razao_original": d["melhoria_relativa"],
                "seed_remedido": seed_novo,
                "final_remedido": cand_novo,
                "razao_remedida": razao,
                "passos": len(d.get("passos") or []),
                "medido_em": time.time(),
                "duracao_s": round(time.time() - t0, 1),
            }
            with destino.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(reg, ensure_ascii=False) + "\n")
            print(
                f"{rotulo:>12} {d['semente']:>3} {d['primary_seed']:>10.3f} {seed_novo:>10.3f} "
                f"{d['melhoria_relativa']:>8.2f}x {razao:>8.2f}x"
            )
    print(f"\n-> {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
