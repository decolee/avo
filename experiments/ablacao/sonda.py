"""O teste dos 100 segundos — `docs/TARGET_DESIGN.md` §3e.

Um alvo serve para comparar arquiteturas de busca só se uma sessão única
alcançar uma **fração** do headroom. A parte que sobra é o espaço onde as
arquiteturas podem diferir; se não sobra nada, não há o que comparar, e a
ablação montada em cima vai gastar milhares de dólares para produzir intervalos
que contêm zero.

O `csv_normalize` passou em todas as outras propriedades — gate com mordida,
custo dimensionado, headroom de 5,1× em 6 movimentos, medição não-trapaceável —
e mesmo assim não separou o AVO completo de uma sessão morta aos cem segundos.
Esta sonda é o que teria contado isso antes, por US$ 0,50.

    python3 experiments/ablacao/sonda.py --alvo csv_normalize

Ela não entra no `make verify` nem no CI: gasta cota e leva minutos. É um passo
da checklist de alvo novo, feito uma vez, com o resultado anotado no
`target.yaml`.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import greedy as G  # noqa: E402
from runner_greedy import _cria_run  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent.parent


def headroom_declarado(alvo: str) -> float:
    import yaml

    data = yaml.safe_load((RAIZ / "targets" / alvo / "target.yaml").read_text(encoding="utf-8"))
    return float(((data or {}).get("lab") or {}).get("headroom_medido") or 0.0)


def main() -> int:
    p = argparse.ArgumentParser(description="Sonda de §3e: uma sessao unica esgota o alvo?")
    p.add_argument("--alvo", required=True)
    p.add_argument("--orcamento-s", type=float, default=100.0)
    p.add_argument("--effort", default="medium")
    p.add_argument("--limite", type=float, default=0.5, help="fracao do headroom que reprova")
    args = p.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="sonda-"))
    try:
        run_dir, erro = _cria_run(args.alvo, tmp / "runs")
        if run_dir is None:
            print(f"nao consegui criar o run: {erro}", file=sys.stderr)
            return 2

        from runner import _estado

        base = _estado(run_dir)["primary"]
        print(f"seed = {base:.3f}; rodando uma sessao de {args.orcamento_s:.0f}s...", flush=True)

        meta = G.roda_greedy(
            args.alvo,
            run_dir,
            timeout_s=args.orcamento_s,
            effort=args.effort,
            log=tmp / "sonda.jsonl",
            perfil="persistente",
        )
        payload = G.avalia(args.alvo, run_dir / "work")
        final = G.primary(payload)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    ganho = final / base if base else 0.0
    teto = headroom_declarado(args.alvo)
    custo = meta.get("total_cost_usd")

    print()
    print(f"  ganho da sonda      {ganho:.2f}x  ({base:.3f} -> {final:.3f})")
    print(f"  headroom declarado  {teto:.2f}x")
    dinheiro = f"US$ {custo:.2f}" if custo else "nao reportado (sessao morta)"
    print(f"  custo               {dinheiro}")
    if not payload.get("correct"):
        print("\n  a sonda terminou INCORRETA — nao conta como fracao do headroom.")
        return 0
    if teto <= 1.0:
        print("\n  sem `lab.headroom_medido` no target.yaml; nao da para julgar a fracao.")
        return 0

    # A fração é medida sobre o GANHO disponível (teto − 1), não sobre o teto:
    # um alvo de 5,1x tem 4,1x de ganho a distribuir, e uma sonda que mede 1,0x
    # capturou zero por cento dele, não vinte.
    fracao = (ganho - 1.0) / (teto - 1.0)
    print(f"  fracao do headroom  {fracao:.0%}")
    if fracao > args.limite:
        print(
            f"\n  REPROVA §3e: uma sessao unica pegou {fracao:.0%} do headroom em "
            f"{args.orcamento_s:.0f}s.\n"
            "  O alvo continua servindo para OTIMIZAR — ele mede melhora de verdade —\n"
            "  mas nao serve para COMPARAR ARQUITETURAS: nao sobra espaco onde os\n"
            "  bracos possam diferir. Veja docs/TARGET_DESIGN.md §3e."
        )
        return 1
    print(f"\n  passa em §3e: sobra {1 - fracao:.0%} do headroom para a busca disputar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
