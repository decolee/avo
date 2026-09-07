"""Piloto do eixo do modelo: quanto o modelo move a curva neste alvo?

Pré-registro em `experiments/FASE_MODELO.md`. Este script NÃO é o experimento —
ele estima efeito e dispersão para decidir se o experimento é pagável, e nenhum
número dele entra em análise.

O desenho é o mais barato que responde a pergunta: o braço de referência **já
está pago**. As 5 sementes do `full` da ablação de 2026-09-06 rodaram
`claude-opus-5` com estes mesmos 8 passos e esta mesma configuração, e estão em
`resultados/ablacao_sql_workload/results.jsonl`. Só falta o outro modelo.

Comparar um run de hoje com um de ontem seria o defeito 9 (deriva de máquina) se
a métrica fosse tempo absoluto. Não é: `melhoria_relativa` é uma razão medida
DENTRO do run, entre o final e o próprio seed daquele run, e a deriva cancela
nela. Isso foi verificado com os dados da ablação — usar denominador fixo em vez
da razão própria PIORA o cv em 3 dos 4 braços.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

import runner as R

AQUI = Path(__file__).resolve().parent
#: Onde o braço de referência já pago vive.
REFERENCIA = AQUI / "resultados" / "ablacao_sql_workload" / "results.jsonl"


def opus_ja_pago() -> list[float]:
    """As 5 sementes do `full` da ablação — o braço de referência, sem custo novo."""
    vals = []
    for linha in REFERENCIA.read_text(encoding="utf-8").splitlines():
        if not linha.strip():
            continue
        d = json.loads(linha)
        if d.get("braco") == "full" and "melhoria_relativa" in d:
            vals.append(d["melhoria_relativa"])
    return vals


def n_necessario(a: list[float], b: list[float]) -> tuple[float, float, float]:
    """(delta, desvio combinado, n por braço) — a mesma fórmula do resto da bancada."""
    if len(a) < 2 or len(b) < 2:
        return (float("nan"),) * 3
    delta = abs(statistics.fmean(a) - statistics.fmean(b))
    s = ((statistics.stdev(a) ** 2 + statistics.stdev(b) ** 2) / 2) ** 0.5
    if delta == 0:
        return delta, s, float("inf")
    return delta, s, 2 * (2.8 * s / delta) ** 2


def main() -> int:
    p = argparse.ArgumentParser(description="Piloto do eixo do modelo")
    p.add_argument("--alvo", default="sql_workload")
    p.add_argument("--modelo", required=True, help="o modelo a comparar contra o de referência")
    p.add_argument("--n", type=int, default=3)
    p.add_argument("--passos", type=int, default=8)
    p.add_argument("--timeout-agente", default="20m")
    p.add_argument("--effort", default="medium")
    p.add_argument("--saida", default=None)
    args = p.parse_args()

    saida = Path(args.saida or (AQUI / "resultados" / f"piloto_modelo_{args.modelo}"))
    saida.mkdir(parents=True, exist_ok=True)
    arquivo = saida / "piloto.jsonl"

    feitos = set()
    if arquivo.is_file():
        for linha in arquivo.read_text(encoding="utf-8").splitlines():
            if linha.strip():
                feitos.add(json.loads(linha)["semente"])

    linhas = (
        [json.loads(x) for x in arquivo.read_text().splitlines() if x.strip()] if feitos else []
    )

    for semente in range(args.n):
        if semente in feitos:
            print(f"  s{semente}: ja feito, pulando", flush=True)
            continue
        t0 = time.time()
        print(f"\n  {args.modelo} s{semente}: rodando...", flush=True)
        reg = R.roda_um(
            "full",
            semente,
            args.alvo,
            args.passos,
            args.timeout_agente,
            saida,
            effort=args.effort,
            modelo=args.modelo,
        )
        reg["modelo"] = args.modelo
        linhas.append(reg)
        with arquivo.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(reg, ensure_ascii=False) + "\n")
        print(
            f"  {args.modelo} s{semente}: {reg.get('melhoria_relativa', 0):.3f}x "
            f"em {time.time() - t0:.0f}s",
            flush=True,
        )

    novos = [d["melhoria_relativa"] for d in linhas if "melhoria_relativa" in d]
    base = opus_ja_pago()
    print("\n" + "=" * 70)
    print(f"PILOTO DO EIXO DO MODELO — {args.alvo}")
    print("=" * 70)
    print(
        f"  claude-opus-5 (referencia, ja paga)  n={len(base):2}  media={statistics.fmean(base):.3f}"
    )
    if len(novos) >= 2:
        print(f"  {args.modelo:36} n={len(novos):2}  media={statistics.fmean(novos):.3f}")
        delta, s, n = n_necessario(novos, base)
        custo = sum(pp.get("custo_usd") or 0 for d in linhas for pp in d.get("passos", []))
        print(f"\n  delta = {delta:.3f}x   ({100 * delta / statistics.fmean(base):.1f}% da base)")
        print(f"  desvio combinado = {s:.3f}")
        print(f"  n por braco para distinguir = {n:.1f}")
        print(f"  custo deste piloto = US$ {custo:.2f}")
        print("\n  criterio do pre-registro (FASE_MODELO.md):")
        if n <= 8:
            print("    n <= 8  -> PAGAVEL: rodar 3 modelos")
        elif n <= 20:
            print("    8 < n <= 20 -> pagavel so para 2 modelos (os extremos)")
        else:
            print("    n > 20  -> NAO RODAR. O eixo do modelo tambem esta abaixo")
            print("              da resolucao desta bancada. Isso e um resultado.")
    else:
        print(f"  {args.modelo}: so {len(novos)} run(s) — insuficiente para dispersao")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
