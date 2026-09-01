"""Análise da ablação, escrita contra o pré-registro.

O método está fixado em `docs/ABLATION_PROTOCOL.md` §6 e não muda depois de ver
os dados: bootstrap para o intervalo da diferença contra `full`, Holm-Bonferroni
sobre as comparações, e o tamanho do efeito reportado sempre junto com o
intervalo. Não há teste t — com n pequeno a normalidade não é verificável.

Reporta também o que a §5b manda reportar: a taxa de falha de agente por braço e
quantos aceites vieram sem mudança de código. Um braço com falha muito diferente
dos outros tem a comparação marcada como não interpretável, porque ali a
diferença mediria o ambiente e não a arquitetura.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from pathlib import Path

AQUI = Path(__file__).resolve().parent
REAMOSTRAGENS = 10_000
REFERENCIA = "full"


def carregar(caminho: Path) -> list[dict]:
    linhas = []
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        if linha.strip():
            d = json.loads(linha)
            if "melhoria_relativa" in d:
                linhas.append(d)
    return linhas


def bootstrap_diferenca(a: list[float], b: list[float], semente: int = 7) -> tuple[float, float]:
    """IC 95% da diferença de médias (a − b), por reamostragem com reposição."""
    rnd = random.Random(semente)
    if not a or not b:
        return (float("nan"), float("nan"))
    amostras = []
    for _ in range(REAMOSTRAGENS):
        ra = [a[rnd.randrange(len(a))] for _ in range(len(a))]
        rb = [b[rnd.randrange(len(b))] for _ in range(len(b))]
        amostras.append(statistics.fmean(ra) - statistics.fmean(rb))
    amostras.sort()
    lo = amostras[int(0.025 * len(amostras))]
    hi = amostras[int(0.975 * len(amostras)) - 1]
    return lo, hi


def p_permutacao(a: list[float], b: list[float], semente: int = 11) -> float:
    """p bilateral por permutação — sem suposição de distribuição."""
    if not a or not b:
        return float("nan")
    observada = abs(statistics.fmean(a) - statistics.fmean(b))
    juntos = a + b
    rnd = random.Random(semente)
    extremos = 0
    for _ in range(REAMOSTRAGENS):
        rnd.shuffle(juntos)
        if (
            abs(statistics.fmean(juntos[: len(a)]) - statistics.fmean(juntos[len(a) :]))
            >= observada
        ):
            extremos += 1
    return (extremos + 1) / (REAMOSTRAGENS + 1)


def holm(pares: list[tuple[str, float]]) -> dict[str, tuple[float, bool]]:
    """Holm-Bonferroni a 5%. Devolve p ajustado e se rejeita a nula."""
    ordenados = sorted(pares, key=lambda kv: kv[1])
    m = len(ordenados)
    saida: dict[str, tuple[float, bool]] = {}
    maior = 0.0
    for i, (nome, p) in enumerate(ordenados):
        ajustado = min(1.0, max(maior, (m - i) * p))
        maior = ajustado
        saida[nome] = (ajustado, ajustado < 0.05)
    return saida


def efeito_minimo(valores: list[float]) -> float:
    """Diferença mínima detectável, aproximada: 2,8 desvios-padrão do erro."""
    if len(valores) < 2:
        return float("nan")
    return 2.8 * statistics.stdev(valores) / math.sqrt(len(valores))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--resultados", default=str(AQUI / "resultados" / "results.jsonl"))
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    caminho = Path(args.resultados)
    if not caminho.is_file():
        print(f"sem resultados em {caminho}")
        return 1
    registros = carregar(caminho)
    if not registros:
        print("nenhum registro completo")
        return 1

    por_braco: dict[str, list[dict]] = {}
    for r in registros:
        por_braco.setdefault(r["braco"], []).append(r)

    resumo = {}
    for braco, rs in sorted(por_braco.items()):
        melhorias = [r["melhoria_relativa"] for r in rs]
        passos = [p for r in rs for p in r.get("passos", [])]
        falhas = sum(1 for p in passos if p.get("agente_ok") is False)
        aceitos = sum(1 for p in passos if p.get("aceito"))
        com_codigo = sum(1 for p in passos if p.get("aceito") and p.get("codigo_mudou") is True)
        custo = sum(p.get("custo_usd") or 0.0 for p in passos)
        resumo[braco] = {
            "n": len(rs),
            "media": statistics.fmean(melhorias),
            "mediana": statistics.median(melhorias),
            "melhorias": melhorias,
            "passos": len(passos),
            "falhas_agente": falhas,
            "taxa_falha": falhas / len(passos) if passos else 0.0,
            "aceitos": aceitos,
            "aceitos_com_codigo_novo": com_codigo,
            "catracas_de_ruido": aceitos - com_codigo,
            "custo_usd": round(custo, 4),
        }

    print("=" * 78)
    print("ABLAÇÃO — resultado primário: melhoria relativa (primary_final / seed)")
    print("=" * 78)
    print(
        f"{'braço':16} {'n':>2} {'média':>7} {'mediana':>8} {'aceitos':>8} {'c/ código':>10} "
        f"{'ruído':>6} {'falhas':>7} {'US$':>7}"
    )
    for braco, d in sorted(resumo.items()):
        print(
            f"{braco:16} {d['n']:>2} {d['media']:>7.3f} {d['mediana']:>8.3f} "
            f"{d['aceitos']:>8} {d['aceitos_com_codigo_novo']:>10} "
            f"{d['catracas_de_ruido']:>6} {d['falhas_agente']:>7} {d['custo_usd']:>7.2f}"
        )

    if REFERENCIA not in resumo:
        print(f"\nsem o braço de referência {REFERENCIA!r}; nada a comparar")
        return 0

    base = resumo[REFERENCIA]["melhorias"]
    print(f"\n{'-' * 78}")
    print(f"Comparações contra `{REFERENCIA}` — bootstrap {REAMOSTRAGENS} reamostragens")
    print(f"{'-' * 78}")
    brutos = []
    for braco, d in sorted(resumo.items()):
        if braco == REFERENCIA:
            continue
        brutos.append((braco, p_permutacao(d["melhorias"], base)))
    ajustados = holm(brutos)

    print(
        f"{'braço':16} {'Δ vs full':>10} {'IC 95%':>22} {'p bruto':>9} {'p Holm':>8} {'rejeita?':>9}"
    )
    for braco, p_bruto in sorted(brutos):
        d = resumo[braco]
        delta = d["media"] - statistics.fmean(base)
        lo, hi = bootstrap_diferenca(d["melhorias"], base)
        p_aj, rejeita = ajustados[braco]
        marca = "sim" if rejeita else "não"
        interpretavel = abs(d["taxa_falha"] - resumo[REFERENCIA]["taxa_falha"]) <= 0.25
        if not interpretavel:
            marca = "N/I"
        print(
            f"{braco:16} {delta:>+10.3f} {f'[{lo:+.3f}, {hi:+.3f}]':>22} "
            f"{p_bruto:>9.4f} {p_aj:>8.4f} {marca:>9}"
        )

    emd = efeito_minimo(base)
    print(
        f"\nEfeito mínimo detectável com n={len(base)} no braço de referência: "
        f"{emd:.3f} (em unidades de melhoria relativa)"
    )
    print("Diferenças abaixo disso este experimento NÃO consegue separar do ruído.")
    print('"Não distinguível do ruído" não é "não existe".')
    print("\nN/I = não interpretável: a taxa de falha de agente difere demais de `full`,")
    print("      então a comparação mediria o ambiente e não a arquitetura.")

    if args.json:
        print("\n" + json.dumps(resumo, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
