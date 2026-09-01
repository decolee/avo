"""Gera os datasets congelados do alvo sessionize.

Este alvo existe para cobrir um eixo que os outros quatro nao tocam: ORDEM. Em
`etl_agg` e `csv_normalize` cada linha e independente das outras, e a ordem de
leitura nao muda nada. Aqui a sessao de um usuario so existe em relacao ao
evento anterior DELE, entao o candidato e obrigado a ordenar — e a escolha de
como ordenar e o espaco de busca.

  perf_curto / perf_longo / perf_denso  -> so medem tempo. Tres formas:
      muitos usuarios com poucos eventos, poucos usuarios com muitos, e um
      volume concentrado em horario de pico (sessoes longas e sobrepostas).
      Uma otimizacao que assume sessoes curtas aparece num regime e some no
      outro.

  gate_adv  -> decide `correct`, e so ele. Pequeno, com os casos que separam
      uma implementacao correta de uma que "funciona nos dados de teste":
      empate exato de timestamp, intervalo EXATAMENTE igual ao limite da sessao
      (o off-by-one classico), evento unico por usuario, usuario com um evento
      so no dataset inteiro, e ids com unicode.

O gerador se recusa a escrever um `gate_adv` que nao consiga distinguir as duas
confusoes mais provaveis: usar `>=` no lugar de `>` na fronteira da sessao, e
ordenar sem criterio de desempate estavel.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from labkit import datakit  # noqa: E402

#: Intervalo que fecha uma sessao, em segundos. 30 minutos e a convencao de
#: analytics; o numero exato nao importa, mas ele estar no CONTRATO importa.
GAP = 1800

PAGINAS = ("/", "/busca", "/produto", "/carrinho", "/checkout", "/conta", "/ajuda", "/blog")
ORIGENS = ("organico", "pago", "email", "direto", "social")


def _evento(rnd: random.Random, uid: str, ts: int, i: int) -> dict:
    return {
        "event_id": i,
        "user_id": uid,
        "ts": ts,
        "page": rnd.choice(PAGINAS),
        "duration_ms": rnd.randrange(200, 120_000),
        "origem": rnd.choice(ORIGENS),
        "device": rnd.choice(("mobile", "desktop", "tablet")),
        "ua": f"agent/{rnd.randrange(1, 40)}.0",
        "ip_hash": f"{rnd.randrange(16**8):08x}",
        "ab_bucket": rnd.randrange(16),
    }


def _write(path: Path, linhas: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for r in linhas:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def _perf(n: int, usuarios: int, seed: int, pico: bool = False) -> list[dict]:
    """Eventos gerados como CADEIA por usuario, e embaralhados no fim.

    Gerar timestamps uniformes em trinta dias produziria quase so sessoes de um
    evento — o alvo ficaria degenerado, sem nada para agrupar. Uma pessoa navega
    em rajadas: varios eventos com poucos minutos entre si, depois horas ou dias
    de silencio. Os intervalos vem dessa mistura, e e ela que faz existirem
    sessoes de verdade.

    O arquivo sai embaralhado: a ordem de leitura nao ajuda o candidato, que
    precisa ordenar por conta propria.
    """
    rnd = random.Random(seed)
    ids = [f"u{i:06d}" for i in range(usuarios)]
    # Intervalos DENTRO da sessao (segundos) e intervalos que a fecham.
    dentro = (5, 15, 30, 60, 120, 300, 600, 1200, 1700)
    fora = (2000, 3600, 7200, 21600, 86400, 172800)
    por_usuario = max(1, n // usuarios)

    linhas = []
    i = 0
    while i < n:
        uid = rnd.choice(ids)
        t = 1_700_000_000 + rnd.randrange(86400 * 30)
        quantos = max(1, int(rnd.gauss(por_usuario, por_usuario / 2)))
        for _ in range(quantos):
            if i >= n:
                break
            linhas.append(_evento(rnd, uid, t, i))
            i += 1
            # No regime de pico as rajadas sao mais longas: a sessao raramente
            # fecha, e o custo se concentra em poucos grupos grandes.
            fecha = rnd.random() < (0.06 if pico else 0.22)
            t += rnd.choice(fora) if fecha else rnd.choice(dentro)
    rnd.shuffle(linhas)
    return linhas


def _adv(seed: int = 4321) -> list[dict]:
    rnd = random.Random(seed)
    linhas: list[dict] = []
    i = 0

    def add(uid: str, ts: int) -> None:
        nonlocal i
        linhas.append(_evento(rnd, uid, ts, i))
        i += 1

    # Corpo comum, embaralhado no fim.
    for u in range(40):
        uid = f"u{u:06d}"
        t = 1_700_000_000 + rnd.randrange(86400)
        for _ in range(rnd.randrange(1, 12)):
            add(uid, t)
            t += rnd.choice((60, 300, 900, GAP - 1, GAP, GAP + 1, 7200))

    # A FRONTEIRA. Um intervalo de exatamente GAP mantem a sessao aberta; GAP+1
    # abre outra. Trocar `>` por `>=` erra so aqui, e so aqui.
    add("BORDA_EXATA", 1_700_100_000)
    add("BORDA_EXATA", 1_700_100_000 + GAP)
    add("BORDA_ACIMA", 1_700_200_000)
    add("BORDA_ACIMA", 1_700_200_000 + GAP + 1)

    # Empate exato de timestamp: dois eventos do mesmo usuario no mesmo segundo.
    # Uma ordenacao sem desempate estavel pode produzir sessoes diferentes entre
    # execucoes — e o resultado tem que ser o mesmo sempre.
    for _ in range(3):
        add("EMPATE", 1_700_300_000)
    add("EMPATE", 1_700_300_000 + 10)

    # Usuario com um unico evento no dataset inteiro.
    add("SOLITARIO", 1_700_400_000)

    # Timestamps de MAGNITUDES diferentes no mesmo usuario. Ordenar `ts` como
    # texto da a ordem certa enquanto todos tem dez digitos, e inverte aqui:
    # "1700700000" < "5" lexicograficamente. E a sujeira que aparece quando o
    # campo vem de origem errada, e sem ela o gate nao distingue ordenacao
    # numerica de ordenacao textual.
    for ts in (5, 900, 1_700_700_000, 1_700_700_060):
        add("EPOCH_MISTO", ts)

    # Unicode no id, e um id que e prefixo de outro.
    add("usuário-ção", 1_700_500_000)
    add("usuário-ção", 1_700_500_000 + 60)
    add("pre", 1_700_600_000)
    add("prefixo", 1_700_600_000)

    rnd.shuffle(linhas)
    return linhas


def _referencia(linhas: list[dict], gap: int = GAP) -> dict:
    por_usuario: dict[str, list[tuple[int, int]]] = {}
    for r in linhas:
        por_usuario.setdefault(r["user_id"], []).append((r["ts"], r["event_id"]))
    saida = {}
    for uid, eventos in por_usuario.items():
        eventos.sort()
        idx, inicio, anterior, n = 0, eventos[0][0], eventos[0][0], 0
        for ts, _ in eventos:
            if ts - anterior > gap:
                saida[f"{uid}|{idx}"] = {"n": n, "inicio": inicio, "fim": anterior}
                idx += 1
                inicio = ts
                n = 0
            anterior = ts
            n += 1
        saida[f"{uid}|{idx}"] = {"n": n, "inicio": inicio, "fim": anterior}
    return saida


def _referencia_ordem_textual(linhas: list[dict]) -> dict:
    """Como ficaria a saida se o `ts` fosse ordenado como texto."""
    por_usuario: dict[str, list] = {}
    for r in linhas:
        por_usuario.setdefault(r["user_id"], []).append((str(r["ts"]), r["event_id"]))
    convertido = {u: [(int(t), e) for t, e in sorted(v)] for u, v in por_usuario.items()}
    saida = {}
    for uid, eventos in convertido.items():
        idx, inicio, anterior, n = 0, eventos[0][0], eventos[0][0], 0
        for ts, _ in eventos:
            if ts - anterior > GAP:
                saida[f"{uid}|{idx}"] = {"n": n, "inicio": inicio, "fim": anterior}
                idx += 1
                inicio = ts
                n = 0
            anterior = ts
            n += 1
        saida[f"{uid}|{idx}"] = {"n": n, "inicio": inicio, "fim": anterior}
    return saida


def _assert_gate_tem_dentes(linhas: list[dict]) -> None:
    """O gate precisa separar `>` de `>=` na fronteira, e nao so isso.

    Uma assercao que so verificasse "existe borda" seria decorativa: o que
    importa e que a borda MUDE o resultado.
    """
    certo = _referencia(linhas)
    frouxo = _referencia(linhas, gap=GAP - 1)  # equivalente a usar >= na fronteira
    if certo == frouxo:
        raise AssertionError(
            "gate_adv nao distingue `>` de `>=` na fronteira da sessao: nenhum par de "
            "eventos esta a exatamente GAP de distancia. O gate seria cego para o "
            "off-by-one mais provavel deste alvo."
        )
    como_texto = _referencia_ordem_textual(linhas)
    if certo == como_texto:
        raise AssertionError(
            "gate_adv nao distingue ordenacao numerica de ordenacao textual do `ts`: "
            "todos os timestamps tem o mesmo numero de digitos. O gate seria cego "
            "para um erro que passa em qualquer dataset limpo."
        )


def _build_adv(path: Path) -> None:
    linhas = _adv()
    _assert_gate_tem_dentes(linhas)
    _write(path, linhas)


def specs() -> list[datakit.DatasetSpec]:
    return [
        datakit.DatasetSpec(
            "perf_curto.jsonl",
            lambda p: _write(p, _perf(30_000, 6000, seed=21)),
            purpose="muitos usuarios, poucos eventos cada",
            rows=30_000,
        ),
        datakit.DatasetSpec(
            "perf_longo.jsonl",
            lambda p: _write(p, _perf(30_000, 300, seed=22)),
            purpose="poucos usuarios, muitos eventos cada",
            rows=30_000,
        ),
        datakit.DatasetSpec(
            "perf_denso.jsonl",
            lambda p: _write(p, _perf(30_000, 1200, seed=23, pico=True)),
            purpose="volume concentrado em pico: sessoes longas e sobrepostas",
            rows=30_000,
        ),
        datakit.DatasetSpec(
            "gate_adv.jsonl",
            _build_adv,
            purpose="UNICO dataset que decide correcao: fronteira exata, empates, bordas",
        ),
    ]


def main() -> int:
    rel = datakit.generate(HERE, specs(), force="--force" in sys.argv)
    print(f"sessionize: {rel.render()}")
    ok, detalhe = datakit.verify_lock(HERE)
    print(f"lock: {detalhe}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
