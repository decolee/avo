"""Gera os datasets congelados do target etl_agg.

Quatro arquivos, dois papéis que não se misturam:

  perf_wide / perf_narrow / perf_skew  -> só medem tempo. Três *formas* de dado,
      não três repetições do mesmo: muitos grupos pequenos, poucos grupos
      grandes, e uma distribuição enviesada onde poucas contas dominam o volume.
      Uma otimização que só ajuda quando os grupos cabem no cache aparece em
      `narrow` e some em `wide` — é isso que torna o score diagnóstico em vez de
      só um número subindo.

  gate_adv  -> decide `correct`, e só ele. Pequeno, 6 casas decimais, notionais
      de fundo e casos de borda explícitos. Um dataset com 2 casas NÃO consegue
      expor arredondamento incremental: a divergência dá exatamente zero. Foi
      essa confusão entre "dado de benchmark" e "dado de gate" que produziu a
      Falha 1.

O registro é largo de propósito — dezesseis campos, como um extrato de ledger de
verdade — enquanto a agregação precisa de cinco. Essa folga é onde mora boa parte
do espaço de busca: `json.loads` paga o preço de materializar o registro inteiro,
e nem todo pipeline precisa pagá-lo.

Garantia de boa-formação: o gerador se recusa a escrever um `gate_adv` que não
consiga detectar arredondamento incremental. A asserção não é decorativa — é a
Falha 1 virada em código. Um dataset de gate que não separa o certo do errado é
pior que nenhum, porque dá a sensação de estar protegido.
"""

from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from labkit import datakit  # noqa: E402

CCY = ("BRL", "USD", "EUR")
STATUS = ("settled", "settled", "settled", "pending", "void")
MERCHANTS = tuple(f"MERCH-{i:04d}" for i in range(400))
CATEGORIES = ("grocery", "fuel", "payroll", "transfer", "fee", "interest", "rent", "tax")
COUNTRIES = ("BR", "US", "DE", "PT", "GB")
CHANNELS = ("pos", "web", "atm", "api", "batch")

#: Campos que a agregação realmente consome. Os outros existem porque existem no
#: mundo, e porque o custo de ignorá-los faz parte do problema.
NEEDED = ("account", "ccy", "amount", "ts", "status")

#: Ordem em que `_record` monta as chaves. Usada so para conferir que o primeiro
#: registro do gate NAO sai nessa ordem.
NEEDED_ORDEM_CANONICA = (
    "id",
    "account",
    "ccy",
    "amount",
    "ts",
    "status",
    "merchant",
    "category",
    "country",
    "channel",
    "fx_rate",
    "memo",
    "batch_id",
    "counterparty",
    "settled_at",
    "source",
)


def _record(rnd: random.Random, i: int, account: str, amount: float, status: str, ts: int) -> dict:
    """Um registro de ledger. A ordem das chaves é fixa mas não é contrato."""
    return {
        "id": i,
        "account": account,
        "ccy": rnd.choice(CCY),
        "amount": amount,
        "ts": ts,
        "status": status,
        "merchant": rnd.choice(MERCHANTS),
        "category": rnd.choice(CATEGORIES),
        "country": rnd.choice(COUNTRIES),
        "channel": rnd.choice(CHANNELS),
        "fx_rate": round(rnd.uniform(0.15, 6.0), 6),
        "memo": f"ref {rnd.randrange(10**9):09d} batch {rnd.randrange(999):03d}",
        "batch_id": rnd.randrange(50_000),
        "counterparty": f"CP{rnd.randrange(9000):04d}",
        "settled_at": 1_700_000_000 + rnd.randrange(86400 * 95),
        "source": "core-ledger-v2",
    }


def _write(path: Path, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _perf_rows(n: int, n_accounts: int, seed: int, skew: bool = False) -> list[dict]:
    rnd = random.Random(seed)
    accounts = [f"ACC{i:05d}" for i in range(n_accounts)]
    rows = []
    for i in range(n):
        if skew:
            # Lei de potência: o volume se concentra numa minoria de contas. É a
            # forma que dado financeiro real tem, e quebra qualquer suposição de
            # grupos uniformemente povoados.
            idx = min(int(abs(rnd.gauss(0, 1)) * n_accounts / 12), n_accounts - 1)
            account = accounts[idx]
        else:
            account = rnd.choice(accounts)
        rows.append(
            _record(
                rnd,
                i,
                account,
                round(rnd.uniform(-5000, 5000), 2),
                rnd.choice(STATUS),
                1_700_000_000 + rnd.randrange(86400 * 90),
            )
        )
    return rows


def _adv_rows(seed: int = 99) -> list[dict]:
    rnd = random.Random(seed)
    accounts = [f"ACC{i:05d}" for i in range(60)]
    rows: list[dict] = []

    # Corpo: 6 casas decimais. É o que sobra de uma conversão de câmbio, e é o
    # que faz o erro de arredondamento incremental existir de fato.
    for i in range(4000):
        rows.append(
            _record(
                rnd,
                i,
                rnd.choice(accounts),
                round(rnd.uniform(-9999, 9999), 6),
                rnd.choice(("settled", "settled", "pending", "void")),
                1_700_000_000 + rnd.randrange(86400 * 90),
            )
        )

    # Notionais de fundo: magnitude ~1e8. float32 tem eps ~8.0 nessa faixa, então
    # um candidato que troque precisão por velocidade é pego aqui.
    for j in range(200):
        row = _record(
            rnd,
            900_000 + j,
            "ACCBIG01",
            round(rnd.uniform(5e7, 5e8), 2),
            "settled",
            1_700_000_000 + j,
        )
        row["ccy"] = "USD"
        rows.append(row)

    # Bordas explícitas, cada uma com um motivo.
    def edge(i: int, account: str, ccy: str, amount: float, ts: int, status: str) -> dict:
        row = _record(rnd, i, account, amount, status, ts)
        row["ccy"] = ccy
        return row

    rows += [
        edge(990_001, "ACC00000", "BRL", 0.005, 1, "settled"),  # meio centavo, duas vezes
        edge(990_002, "ACC00000", "BRL", 0.005, 2, "settled"),
        edge(990_003, "ACC00000", "BRL", -0.004999, 3, "pending"),  # conta em gross, não em net
        edge(990_004, "ACC99999", "JPY", 1e-06, 4, "settled"),  # moeda fora do conjunto perf
        edge(990_005, "ACC99999", "JPY", -1e-06, 4, "void"),  # empate exato em ts
        edge(990_006, "ACCZERO1", "EUR", 1234.5, 9, "pending"),  # net = 0 com gross != 0
        edge(990_007, "ACCZERO1", "EUR", -1234.5, 8, "void"),
    ]
    return rows


def _assert_dataset_has_teeth(rows: list[dict]) -> None:
    """Prova que este dataset separa a soma correta da soma arredondada a cada passo.

    A referência soma com `math.fsum` (soma exatamente arredondada) e arredonda
    no final; o mutante arredonda a cada acumulação. Se os dois concordarem em
    todos os grupos, o dataset é cego para a Falha 1 e não serve como gate.
    """
    incremental: dict[str, float] = {}
    parts: dict[str, list[float]] = {}
    for r in rows:
        key = r["account"] + "|" + r["ccy"]
        parts.setdefault(key, []).append(r["amount"])
        incremental[key] = round(incremental.get(key, 0.0) + r["amount"], 2)
    truth = {key: round(math.fsum(values), 2) for key, values in parts.items()}

    divergent = [abs(truth[k] - incremental[k]) for k in truth if truth[k] != incremental[k]]
    if not divergent:
        raise AssertionError(
            "gate_adv não distingue arredondamento incremental de arredondamento final: "
            "o dataset é cego para a Falha 1. Aumente as casas decimais ou os grupos."
        )
    if max(divergent) < 0.01:
        raise AssertionError(
            f"gate_adv diverge no máximo {max(divergent):.4f} — menos de um centavo, dentro "
            "do que qualquer tolerância razoável perdoa. O gate não teria mordida."
        )


def _permutar_ordem_dos_campos(rows: list[dict], seed: int = 4242) -> list[dict]:
    """Embaralha a ORDEM das chaves de parte dos registros do gate.

    A ordem dos campos nao esta em `kb/00-contrato.md` e nao e propriedade do
    formato — e propriedade deste arquivo. Enquanto `gate_adv` e os `perf_*`
    sairem do mesmo gerador com a mesma ordem, um candidato que assume ordem
    passa no gate com folga, e o gate existe justamente para achar suposicoes
    sobre a forma do dado.

    Isso nao e hipotetico: um run real (`experiments/RESULTS-etl_agg-20260901.md`)
    encontrou uma regex que assume ordem, mede +28,6% sobre o melhor candidato
    honesto, e passava. Era o maior ganho disponivel na curva e vinha inteiro da
    suposicao.

    O primeiro registro ja vem permutado de proposito: um candidato posicional
    falha na primeira linha, com erro claro, em vez de falhar no meio.

    Permutar so uma PARTE mantem a ordem canonica representada tambem, para que
    o gate exercite os dois casos.
    """
    rnd = random.Random(seed)
    out = []
    for i, row in enumerate(rows):
        if i % 3 == 0:
            chaves = list(row)
            rnd.shuffle(chaves)
            out.append({k: row[k] for k in chaves})
        else:
            out.append(row)
    return out


def _build_adv(path: Path) -> None:
    rows = _permutar_ordem_dos_campos(_adv_rows())
    _assert_dataset_has_teeth(rows)
    _assert_ordem_permutada(rows)
    _write(path, rows)


def _assert_ordem_permutada(rows: list[dict]) -> None:
    """Prova que o gate consegue reprovar um candidato posicional.

    Se todos os registros sairem na mesma ordem de chaves, a defesa e decorativa.
    """
    ordens = {tuple(r) for r in rows}
    if len(ordens) < 2:
        raise AssertionError(
            "gate_adv tem uma unica ordem de campos: um candidato que assume ordem "
            "passaria. A permutacao nao esta fazendo efeito."
        )
    if tuple(rows[0]) == tuple(NEEDED_ORDEM_CANONICA):
        raise AssertionError(
            "o primeiro registro do gate_adv esta na ordem canonica; um candidato "
            "posicional so falharia mais adiante, com erro menos obvio."
        )


def specs() -> list[datakit.DatasetSpec]:
    return [
        datakit.DatasetSpec(
            "perf_wide.jsonl",
            lambda p: _write(p, _perf_rows(25_000, 3000, seed=11)),
            purpose="muitos grupos pequenos (~4500 grupos)",
            rows=25_000,
        ),
        datakit.DatasetSpec(
            "perf_narrow.jsonl",
            lambda p: _write(p, _perf_rows(25_000, 50, seed=12)),
            purpose="poucos grupos grandes (~150 grupos)",
            rows=25_000,
        ),
        datakit.DatasetSpec(
            "perf_skew.jsonl",
            lambda p: _write(p, _perf_rows(25_000, 800, seed=13, skew=True)),
            purpose="distribuicao enviesada: poucas contas concentram o volume",
            rows=25_000,
        ),
        datakit.DatasetSpec(
            "gate_adv.jsonl",
            _build_adv,
            purpose="UNICO dataset que decide correcao: 6 casas, notionais grandes, bordas",
            rows=4207,
        ),
    ]


def main() -> int:
    report = datakit.generate(HERE, specs(), force="--force" in sys.argv)
    print(f"etl_agg: {report.render()}")
    ok, detail = datakit.verify_lock(HERE)
    print(f"lock: {detail}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
