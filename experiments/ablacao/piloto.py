"""Piloto de potência — estimar a variância ANTES de desenhar o experimento.

Os dois experimentos anteriores deste laboratório (`ABLATION.md`, US$ 168;
`CONTROLE.md`, US$ 175) não distinguiram nada, e nos dois a razão foi a mesma:
o desenho foi escolhido pelo orçamento e o poder estatístico foi conferido
depois. US$ 343 para descobrir que o n estava errado.

Este arquivo inverte a ordem. Ele mede duas coisas baratas e usa as duas para
calcular o n do experimento de verdade:

  1. o desvio do `greedy` entre sementes, com sessões curtas
  2. a curva por passo de UM run do `full`, que dá a forma da trajetória, o
     custo por passo neste alvo, e se o supervisor chega a disparar

Não é um experimento: nenhuma hipótese é testada aqui, e nada do que sai daqui
entra na análise principal. É orçamento gasto para saber quanto orçamento gastar.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import greedy as G  # noqa: E402
import runner as R  # noqa: E402
from runner_greedy import _codigo_mudou, _cria_run  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent.parent
AQUI = Path(__file__).resolve().parent


def um_greedy(alvo: str, semente: int, saida: Path, orcamento_s: float, effort: str) -> dict:
    run_dir, erro = _cria_run(alvo, saida / "runs" / f"pil_greedy-s{semente}")
    if run_dir is None:
        return {"braco": "pil_greedy", "semente": semente, "erro": erro}
    base = R._estado(run_dir)["primary"]
    meta = G.roda_greedy(
        alvo,
        run_dir,
        timeout_s=orcamento_s,
        effort=effort,
        log=saida / "logs" / f"pil_greedy-s{semente}.jsonl",
        perfil="persistente",
    )
    payload = G.avalia(alvo, run_dir / "work")
    final = G.primary(payload)
    return {
        "braco": "pil_greedy",
        "semente": semente,
        "alvo": alvo,
        "primary_seed": base,
        "primary_final": final,
        "melhoria_relativa": final / (base or 1e-9),
        "correct": bool(payload.get("correct")),
        "codigo_mudou": _codigo_mudou(run_dir, alvo, R._entrypoint(alvo)),
        "custo_usd": meta.get("total_cost_usd"),
        "turnos": meta.get("num_turns"),
        "dur_agente_s": meta.get("duration_s"),
        "morto_por_tempo": bool(meta.get("morto_por_tempo")),
        "orcamento_s": orcamento_s,
    }


def n_necessario(desvio: float, delta: float) -> float:
    """Sementes por braço para 5% e poder 80%, dois grupos: n ≈ 2·(2,8·s/Δ)²."""
    if not desvio or not delta:
        return float("nan")
    return 2.0 * (2.8 * desvio / abs(delta)) ** 2


def relatorio(linhas: list[dict]) -> None:
    greedy = [d for d in linhas if d.get("braco") == "pil_greedy" and "melhoria_relativa" in d]
    full = [d for d in linhas if d.get("braco") == "full" and d.get("passos")]

    print("\n" + "=" * 78)
    print("PILOTO — o que estes numeros servem para decidir")
    print("=" * 78)

    if greedy:
        g = [d["melhoria_relativa"] for d in greedy]
        dp = statistics.stdev(g) if len(g) > 1 else float("nan")
        print(f"\n`greedy` n={len(g)}: media {statistics.fmean(g):.3f}x, desvio {dp:.3f}")
        print("  " + ", ".join(f"{x:.2f}x" for x in sorted(g)))
        custos = [d["custo_usd"] for d in greedy if d.get("custo_usd")]
        if custos:
            print(f"  custo medio US$ {statistics.fmean(custos):.2f} por sessao")

    for d in full:
        base = d.get("primary_seed") or 1e-9
        print(f"\n`full` s{d['semente']} — trajetoria por passo (ganho contra o proprio seed):")
        acum_s = acum_usd = 0.0
        for p in d["passos"]:
            acum_s += float(p.get("dur_agente_s") or 0.0)
            acum_usd += float(p.get("custo_usd") or 0.0)
            marca = "sup" if p.get("supervisor") else "   "
            mudou = "cod" if p.get("codigo_mudou") else "   "
            print(
                f"   passo {p['passo']:>2}  {p['primary_depois'] / base:>6.2f}x  "
                f"{acum_s:>6.0f}s  US$ {acum_usd:>6.2f}  "
                f"{'ACEITO' if p.get('aceito') else '  --  '} {marca} {mudou}"
            )
        disparos = sum(1 for p in d["passos"] if p.get("supervisor"))
        print(f"   supervisor disparou {disparos}x em {len(d['passos'])} passos")

    if greedy and len(greedy) > 1 and full:
        dp = statistics.stdev([d["melhoria_relativa"] for d in greedy])
        media_g = statistics.fmean([d["melhoria_relativa"] for d in greedy])
        print("\n" + "-" * 78)
        print("DIMENSIONAMENTO — n por braco para detectar um efeito de tamanho X")
        print("-" * 78)
        print("Usa o desvio do `greedy` como estimativa; o do `full` costuma ser MENOR")
        print("(o gate trunca a amostra ruim), entao isto e conservador.\n")
        print(f"{'efeito':>10} {'em ganho':>10} {'n por braco':>12} {'US$ estimado':>14}")
        custo_full = sum(float(p.get("custo_usd") or 0.0) for d in full for p in d["passos"]) / len(
            full
        )
        for pct in (0.05, 0.10, 0.15, 0.20, 0.30):
            delta = media_g * pct
            n = n_necessario(dp, delta)
            print(
                f"{pct:>9.0%} {delta:>9.2f}x {n:>12.0f} {2 * n * custo_full:>13,.0f}"
                if math.isfinite(n)
                else ""
            )
        print(f"\n  (custo de um run do `full` neste piloto: US$ {custo_full:.2f})")


def main() -> int:
    p = argparse.ArgumentParser(description="Piloto de potencia — mede variancia, nao hipotese")
    p.add_argument("--alvo", default="sql_agg")
    p.add_argument("--greedy-n", type=int, default=5)
    p.add_argument("--greedy-orcamento-s", type=float, default=600.0)
    p.add_argument("--full-n", type=int, default=1)
    p.add_argument("--full-passos", type=int, default=8)
    p.add_argument("--janela-estagnacao", type=int, default=2)
    p.add_argument("--timeout-agente", default="20m")
    p.add_argument("--effort", default="medium")
    p.add_argument("--saida", default=None)
    p.add_argument("--so-relatorio", action="store_true")
    args = p.parse_args()

    saida = Path(args.saida or (AQUI / "resultados" / f"piloto_{args.alvo}"))
    saida.mkdir(parents=True, exist_ok=True)
    arquivo = saida / "piloto.jsonl"

    linhas = []
    if arquivo.is_file():
        linhas = [
            json.loads(x) for x in arquivo.read_text(encoding="utf-8").splitlines() if x.strip()
        ]
    feitos = {(d.get("braco"), d.get("semente")) for d in linhas}

    if args.so_relatorio:
        relatorio(linhas)
        return 0

    # Ordem deliberada: o `greedy` primeiro, porque e barato e ja da o desvio.
    # Se algo derrubar o container no meio, o numero que dimensiona o experimento
    # ja esta no disco.
    trabalhos: list[tuple[str, int]] = [("pil_greedy", i) for i in range(args.greedy_n)]
    trabalhos += [("full", i) for i in range(args.full_n)]

    for braco, semente in trabalhos:
        if (braco, semente) in feitos:
            print(f"  {braco} s{semente}: ja feito, pulando", flush=True)
            continue
        t0 = time.time()
        print(f"\n  {braco} s{semente}: rodando...", flush=True)
        if braco == "full":
            reg = R.roda_um(
                "full",
                semente,
                args.alvo,
                args.full_passos,
                args.timeout_agente,
                saida,
                effort=args.effort,
                janela_estagnacao=args.janela_estagnacao,
            )
        else:
            reg = um_greedy(args.alvo, semente, saida, args.greedy_orcamento_s, args.effort)
        reg["braco"] = braco
        linhas.append(reg)
        with arquivo.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(reg, ensure_ascii=False) + "\n")
        print(
            f"  {braco} s{semente}: {reg.get('melhoria_relativa', 0):.2f}x "
            f"em {time.time() - t0:.0f}s",
            flush=True,
        )
        subprocess.run(
            ["git", "add", str(arquivo)], cwd=str(RAIZ), check=False, capture_output=True
        )
        subprocess.run(
            [
                "git",
                "commit",
                "-q",
                "--no-verify",
                "-m",
                f"piloto {args.alvo}: {braco} s{semente} ({reg.get('melhoria_relativa', 0):.2f}x)",
            ],
            cwd=str(RAIZ),
            check=False,
            capture_output=True,
        )

    relatorio(linhas)
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    raise SystemExit(main())
