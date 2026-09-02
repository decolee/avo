"""Análise do controle honesto: a curva de custo × ganho do `full` e do `greedy`.

`analise.py` compara braços num ponto só, que é o desenho certo quando os braços
consomem o mesmo compute. Aqui não consomem: o `greedy` natural para sozinho em
~700s e o `full` gasta ~2470s. Comparar os pontos finais mediria as duas coisas
ao mesmo tempo — a arquitetura e o orçamento — e atribuiria tudo à arquitetura.

Então a comparação é entre CURVAS, pareadas por compute. Do lado do `full` a
curva sai de graça: cada semente registra o score depois de cada passo, e o
tempo de agente acumulado até ali. Do lado do `greedy`, cada ponto é uma sessão
com orçamento declarado.

O que esta análise pode concluir, e o que não pode:

  pode   "no orçamento X, a diferença entre os dois é D, com IC [a, b]"
  pode   "a diferença é menor que o efeito mínimo detectável com este n"
  NÃO    "não há diferença" — ausência de evidência não é evidência de ausência,
         e com n desta ordem o intervalo é largo por construção

O método vem do pré-registro (`docs/ABLATION_PROTOCOL.md` §6) e não muda depois
de ver os dados: bootstrap para o intervalo, permutação para o p, Holm para a
multiplicidade, e o efeito mínimo detectável reportado sempre junto.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path

from analise import bootstrap_diferenca, efeito_minimo, holm, p_permutacao

AQUI = Path(__file__).resolve().parent


def carregar(caminho: Path) -> list[dict]:
    if not caminho.is_file():
        return []
    saida = []
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        if linha.strip():
            d = json.loads(linha)
            if "melhoria_relativa" in d:
                saida.append(d)
    return saida


def curva_do_full(linhas: list[dict]) -> dict[int, list[dict]]:
    """Pontos (compute acumulado, custo acumulado, ganho) depois de cada passo.

    O ganho é sempre relativo ao seed DA PRÓPRIA semente. Cada run mede o seed na
    mesma máquina e no mesmo instante em que roda, então a razão cancela a deriva
    da máquina — que é grande o bastante para importar: os seeds medidos variam
    entre 2.27 e 2.47 sem nada ter mudado no código.
    """
    por_passo: dict[int, list[dict]] = {}
    for d in linhas:
        if d.get("braco") != "full":
            continue
        base = d.get("primary_seed") or 0.0
        if base <= 0:
            continue
        compute = custo = 0.0
        custo_incompleto = False
        for passo in d.get("passos") or []:
            compute += float(passo.get("dur_agente_s") or 0.0)
            c = passo.get("custo_usd")
            if c is None:
                # O harness não reporta custo de um agente morto por timeout. O
                # trabalho foi feito e cobrado; só o número não voltou. Marcar é
                # mais honesto que somar zero e chamar de custo.
                custo_incompleto = True
            else:
                custo += float(c)
            por_passo.setdefault(int(passo["passo"]), []).append(
                {
                    "semente": d.get("semente"),
                    "compute_s": compute,
                    "custo_usd": custo,
                    "custo_incompleto": custo_incompleto,
                    "ganho": float(passo.get("primary_depois") or 0.0) / base,
                    "primary_seed": base,
                }
            )
    return por_passo


def curva_do_greedy(linhas: list[dict]) -> dict[str, list[dict]]:
    por_braco: dict[str, list[dict]] = {}
    for d in linhas:
        braco = d.get("braco") or ""
        if not braco.startswith("greedy"):
            continue
        passo = (d.get("passos") or [{}])[0]
        por_braco.setdefault(braco, []).append(
            {
                "semente": d.get("semente"),
                "compute_s": float(passo.get("dur_agente_s") or 0.0),
                "custo_usd": float(passo.get("custo_usd") or 0.0),
                "custo_incompleto": passo.get("custo_usd") is None,
                "ganho": float(d.get("melhoria_relativa") or 0.0),
                "primary_seed": float(d.get("primary_seed") or 0.0),
                "orcamento_s": d.get("orcamento_s"),
                "morto_por_tempo": bool(passo.get("morto_por_tempo")),
                "codigo_mudou": d.get("codigo_mudou"),
                "correct": d.get("correct"),
            }
        )
    return por_braco


def taxa_usd_por_segundo(pontos: list[dict]) -> float:
    """US$ por segundo de agente, mediana sobre as sessões com custo medido.

    Serve para imputar o custo das sessões que o timeout matou: o harness só
    reporta `total_cost_usd` no evento `result`, e uma sessão morta antes dele
    volta com `None`. Somar esse `None` como zero — que era o que este arquivo
    fazia — faz o braço parecer mais barato do que foi, e o erro cresce
    justamente nos braços de orçamento curto, que são os que mais morrem.

    A imputação é segura aqui porque a taxa é notavelmente estável: US$ 0,0049/s
    no `greedy_b600`, 0,0053 no `greedy_bmax`, 0,0058 na calibração e 0,0049 por
    passo do `full`. Mesmo assim ela é marcada, e o relatório diz quantos pontos
    foram imputados.
    """
    taxas = [
        p["custo_usd"] / p["compute_s"]
        for p in pontos
        if not p["custo_incompleto"] and p["compute_s"] > 0 and p["custo_usd"] > 0
    ]
    return statistics.median(taxas) if taxas else 0.0


def _resumo(pontos: list[dict], taxa: float = 0.0) -> dict:
    ganhos = [p["ganho"] for p in pontos]
    custos = [(p["compute_s"] * taxa if p["custo_incompleto"] else p["custo_usd"]) for p in pontos]
    return {
        "n": len(pontos),
        "compute_s": statistics.fmean(p["compute_s"] for p in pontos) if pontos else 0.0,
        "custo_usd": statistics.fmean(custos) if custos else 0.0,
        "ganho": statistics.fmean(ganhos) if ganhos else 0.0,
        "ganho_dp": statistics.stdev(ganhos) if len(ganhos) > 1 else float("nan"),
        "mde": efeito_minimo(ganhos),
        "ganhos": ganhos,
        "custo_imputado": sum(1 for p in pontos if p["custo_incompleto"]),
    }


def _mais_proximo(alvo: float, curva: dict[int, dict], eixo: str) -> int | None:
    """O passo do `full` mais próximo de `alvo` no eixo dado.

    Dois eixos, e eles discordam. `greedy_cont` s0 gastou 2211s contra 2746s do
    `full` — pareado no relógio — mas custou US$ 18,27 contra US$ 12,05, porque
    cada retomada reenvia o contexto inteiro. Parear só por segundos esconderia
    que o braço que está ganhando é 50% mais caro; parear só por dólar esconderia
    que ele usou menos máquina. O relatório faz os dois.
    """
    if not curva:
        return None
    return min(curva, key=lambda k: abs(curva[k][eixo] - alvo))


def main() -> int:
    p = argparse.ArgumentParser(description="Curva de custo x ganho: full contra greedy")
    p.add_argument("--resultados", default=str(AQUI / "resultados" / "results.jsonl"))
    p.add_argument("--greedy", default=str(AQUI / "resultados" / "greedy.jsonl"))
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    full = carregar(Path(args.resultados))
    greedy = carregar(Path(args.greedy))
    if not full:
        print(f"sem resultados do full em {args.resultados}")
        return 1

    passos = curva_do_full(full)
    pontos_greedy = curva_do_greedy(greedy)
    todos = [x for v in passos.values() for x in v] + [x for v in pontos_greedy.values() for x in v]
    taxa = taxa_usd_por_segundo(todos)
    curva_full = {k: _resumo(v, taxa) for k, v in sorted(passos.items())}
    curva_greedy = {k: _resumo(v, taxa) for k, v in sorted(pontos_greedy.items())}

    print("=" * 78)
    print("CURVA DO `full` — ganho depois de cada passo, contra o seed da propria semente")
    print("=" * 78)
    print(
        f"taxa observada: US$ {taxa:.4f} por segundo de agente "
        "(usada para imputar sessoes mortas antes do evento de custo)\n"
    )
    print(
        f"{'passo':>6} {'n':>3} {'compute':>9} {'US$':>7} {'ganho':>8} {'dp':>7} {'MDE':>7} {'imp':>4}"
    )
    for k, r in curva_full.items():
        print(
            f"{k:>6} {r['n']:>3} {r['compute_s']:>8.0f}s {r['custo_usd']:>7.2f} "
            f"{r['ganho']:>7.2f}x {r['ganho_dp']:>7.2f} {r['mde']:>7.2f} {r['custo_imputado']:>4}"
        )

    if not curva_greedy:
        print("\n(sem dados do greedy ainda)")
        return 0

    print()
    print("=" * 78)
    print("CURVA DO `greedy` — uma sessao unica por ponto, sem lineage nem gate")
    print("=" * 78)
    print(
        f"{'braco':>13} {'n':>3} {'compute':>9} {'US$':>7} {'ganho':>8} "
        f"{'dp':>7} {'MDE':>7} {'kill':>5} {'imp':>4}"
    )
    for nome, r in curva_greedy.items():
        mortos = sum(1 for x in pontos_greedy[nome] if x["morto_por_tempo"])
        print(
            f"{nome:>13} {r['n']:>3} {r['compute_s']:>8.0f}s {r['custo_usd']:>7.2f} "
            f"{r['ganho']:>7.2f}x {r['ganho_dp']:>7.2f} {r['mde']:>7.2f} {mortos:>5} "
            f"{r['custo_imputado']:>4}"
        )

    # A comparação: cada ponto do greedy contra o passo do full de compute mais
    # próximo. Parear por compute é o que separa "a arquitetura ajuda" de "quem
    # gastou mais ganhou".
    print()
    print("=" * 78)
    print("COMPARACAO PAREADA — full(passo k) menos greedy(orcamento)")
    print("=" * 78)
    print("Dois pareamentos, porque os eixos discordam: o `greedy_cont` gasta menos")
    print("relogio e mais dolar que o `full`. Um resultado que so sobrevive num dos")
    print("dois eixos e um resultado sobre o eixo, nao sobre a arquitetura.\n")
    comparacoes = []
    for eixo, rotulo, fmt in (
        ("compute_s", "relogio", "{:.0f}s"),
        ("custo_usd", "dolar", "US$ {:.2f}"),
    ):
        for nome, rg in curva_greedy.items():
            k = _mais_proximo(rg[eixo], curva_full, eixo)
            if k is None:
                continue
            rf = curva_full[k]
            dif = rf["ganho"] - rg["ganho"]
            lo, hi = bootstrap_diferenca(rf["ganhos"], rg["ganhos"])
            pv = p_permutacao(rf["ganhos"], rg["ganhos"])
            comparacoes.append(
                {
                    "eixo": rotulo,
                    "chave": f"{nome}@{rotulo}",
                    "greedy": nome,
                    "full_passo": k,
                    "greedy_x": rg[eixo],
                    "full_x": rf[eixo],
                    "fmt": fmt,
                    "desbalanco": (rf[eixo] - rg[eixo]) / max(rg[eixo], 1e-9),
                    "diferenca": dif,
                    "ic": (lo, hi),
                    "p": pv,
                    "mde": max(rf["mde"], rg["mde"]),
                }
            )

    ajustados = holm([(c["chave"], c["p"]) for c in comparacoes])
    comparacoes.sort(key=lambda c: (c["eixo"], c["greedy"]))
    eixo_atual = ""
    for c in comparacoes:
        if c["eixo"] != eixo_atual:
            eixo_atual = c["eixo"]
            print(f"\n  ——— pareado por {eixo_atual} ———")
        pa, rejeita = ajustados[c["chave"]]
        marca = "SIM" if rejeita else "nao"
        print(
            f"\n  {c['greedy']} ({c['fmt'].format(c['greedy_x'])}) "
            f"vs full passo {c['full_passo']} ({c['fmt'].format(c['full_x'])}), "
            f"desbalanco {c['desbalanco']:+.0%}"
        )
        print(
            f"    diferenca {c['diferenca']:+.3f}x   IC95 [{c['ic'][0]:+.3f}, {c['ic'][1]:+.3f}]"
            f"   p={c['p']:.3f} (Holm {pa:.3f}) -> distinguivel: {marca}"
        )
        if not rejeita and abs(c["diferenca"]) < c["mde"]:
            print(
                f"    a diferenca ({abs(c['diferenca']):.3f}) esta ABAIXO do efeito minimo "
                f"detectavel ({c['mde']:.3f}) com este n — o experimento nao tinha"
            )
            print("    resolucao para achar um efeito deste tamanho. Nao e evidencia de empate.")

    # Deriva da máquina: os seeds são o mesmo código medido em momentos
    # diferentes, então a variação entre eles é ruído do ambiente, puro. Se ela
    # for da ordem das diferenças entre braços, nada aqui é interpretável.
    seeds_full_velho = [
        d["primary_seed"] for d in full if d.get("braco") == "full" and (d.get("semente") or 0) < 4
    ]
    seeds_full_novo = [
        d["primary_seed"] for d in full if d.get("braco") == "full" and (d.get("semente") or 0) >= 4
    ]
    seeds_greedy = [d["primary_seed"] for d in greedy if d.get("primary_seed")]
    print()
    print("=" * 78)
    print("DERIVA DA MAQUINA — o seed e o mesmo codigo; o que varia e o ambiente")
    print("=" * 78)
    for rotulo, vals in (
        ("full sementes 0-3 (outro dia)", seeds_full_velho),
        ("full sementes 4+ (esta janela)", seeds_full_novo),
        ("greedy (esta janela)", seeds_greedy),
    ):
        if vals:
            dp = statistics.stdev(vals) if len(vals) > 1 else float("nan")
            print(
                f"  {rotulo:<32} n={len(vals):<3} media={statistics.fmean(vals):.3f} "
                f"dp={dp:.3f} min={min(vals):.3f} max={max(vals):.3f}"
            )
    if seeds_full_velho and seeds_full_novo:
        delta = statistics.fmean(seeds_full_novo) - statistics.fmean(seeds_full_velho)
        print(
            f"\n  deriva entre as duas janelas: {delta:+.3f} "
            f"({delta / statistics.fmean(seeds_full_velho):+.1%} do seed)"
        )
        print("  O ganho e razao contra o seed da propria semente, entao a deriva cancela")
        print("  em primeira ordem. Ela e reportada porque cancelar em primeira ordem nao")
        print("  e cancelar: se a maquina satura, o teto do ganho se move junto.")

    if args.json:
        print()
        print(
            json.dumps(
                {
                    "full": {
                        str(k): {x: y for x, y in v.items() if x != "ganhos"}
                        for k, v in curva_full.items()
                    },
                    "greedy": {
                        k: {x: y for x, y in v.items() if x != "ganhos"}
                        for k, v in curva_greedy.items()
                    },
                    "comparacoes": [c | {"p_holm": ajustados[c["greedy"]][0]} for c in comparacoes],
                },
                ensure_ascii=False,
                indent=2,
                default=lambda o: None if isinstance(o, float) and math.isnan(o) else str(o),
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
