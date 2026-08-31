"""f(x) do target etl_agg — o árbitro. Nunca afrouxe isto para um candidato passar.

Separação deliberada entre gate e benchmark:

  CORREÇÃO    -> data/gate_adv.jsonl. Pequeno, 6 casas decimais, notionais de
                 fundo. É o ÚNICO dataset que decide `correct`.
  PERFORMANCE -> data/perf_*.jsonl. Grandes, 2 casas. Só medem tempo.

Um dataset com 2 casas decimais não consegue expor arredondamento incremental:
os `amount` já são múltiplos de um centavo, o erro acumulado cabe dentro do
`round(x, 2)` final e a divergência dá exatamente zero. Gate e benchmark têm
requisitos opostos e não devem compartilhar dados — foi essa confusão que
produziu a Falha 1.

COMO A CORREÇÃO É DECIDIDA, e por que não é por hash de igualdade exata.

A tentação é comparar o SHA256 da saída do candidato com o da referência. O
problema é que a referência também soma em ponto flutuante: quando a soma
verdadeira de um grupo cai perto de uma fronteira de meio centavo, somar da
esquerda para a direita e somar com `math.fsum` arredondam para centavos
diferentes. O gate reprovaria código correto por causa da ordem da soma — e
reprovar candidato bom é tão danoso quanto aprovar candidato ruim, porque a
busca aprende a coisa errada.

Então o contrato é declarado em dois pedaços, cada um verificado do seu jeito:

  VALOR         `gross` tem que estar a menos de meio centavo da soma
                verdadeira do grupo (calculada com `math.fsum`, que é a soma
                exatamente arredondada), mais uma folga proporcional à
                magnitude do grupo. Arredondamento incremental erra por
                centésimos e é pego; ordem de soma erra por 1e-10 e passa.
  APRESENTAÇÃO  o número devolvido tem que ser de fato um valor de dois
                decimais. Sem isso um candidato passaria devolvendo a soma crua.

O hash continua sendo calculado e aparece em `notes` como impressão digital —
útil para ver de relance que duas versões produzem a mesma saída — mas não é
ele que decide.
"""

from __future__ import annotations

import json
import math
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from labkit import contracts, datakit, evalkit  # noqa: E402

ENTRYPOINT = "transform.py"
SYMBOL = "transform"

PERF_FILES = ("perf_wide.jsonl", "perf_narrow.jsonl", "perf_skew.jsonl")
GATE_FILE = "gate_adv.jsonl"

#: Meio centavo: o máximo que um arredondamento correto para 2 casas pode
#: afastar o valor apresentado da soma verdadeira.
HALF_CENT = 0.005

#: Fator de folga sobre o erro de ponto flutuante teórico de uma soma sequencial
#: (n * eps * soma_dos_modulos). Generoso o bastante para qualquer ordem de soma
#: sensata, pequeno o bastante para não perdoar um centavo.
FP_SLACK = 8.0


def data(name: str) -> Path:
    return datakit.data_dir(HERE) / name


# ----------------------------------------------------------------- referência


def reference(path):
    """A implementação correta. Soma com `fsum` e arredonda no final."""
    parts: dict[str, dict] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            key = row["account"] + "|" + row["ccy"]
            acc = parts.get(key)
            if acc is None:
                parts[key] = acc = {"n": 0, "gross": [], "net": [], "last_ts": 0}
            acc["n"] += 1
            acc["gross"].append(row["amount"])
            if row["status"] == "settled":
                acc["net"].append(row["amount"])
            if row["ts"] > acc["last_ts"]:
                acc["last_ts"] = row["ts"]
    return {
        key: {
            "n": acc["n"],
            "gross": round(math.fsum(acc["gross"]), 2),
            "net": round(math.fsum(acc["net"]), 2),
            "last_ts": acc["last_ts"],
        }
        for key, acc in parts.items()
    }


def _truth(path):
    """Somas verdadeiras (não arredondadas) e a folga de ponto flutuante por grupo."""
    parts: dict[str, dict] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            key = row["account"] + "|" + row["ccy"]
            acc = parts.get(key)
            if acc is None:
                parts[key] = acc = {"n": 0, "gross": [], "net": [], "last_ts": 0, "mag": 0.0}
            acc["n"] += 1
            acc["gross"].append(row["amount"])
            acc["mag"] += abs(row["amount"])
            if row["status"] == "settled":
                acc["net"].append(row["amount"])
            if row["ts"] > acc["last_ts"]:
                acc["last_ts"] = row["ts"]

    out = {}
    for key, acc in parts.items():
        slack = FP_SLACK * sys.float_info.epsilon * acc["mag"] * max(acc["n"], 1)
        out[key] = {
            "n": acc["n"],
            "gross": math.fsum(acc["gross"]),
            "net": math.fsum(acc["net"]),
            "last_ts": acc["last_ts"],
            "tol": HALF_CENT + slack,
        }
    return out


_TRUTH_CACHE: dict | None = None


def truth():
    global _TRUTH_CACHE
    if _TRUTH_CACHE is None:
        _TRUTH_CACHE = _truth(data(GATE_FILE))
    return _TRUTH_CACHE


# ----------------------------------------------------------------------- gate


def _is_two_decimals(value) -> bool:
    try:
        scaled = float(value) * 100.0
    except (TypeError, ValueError):
        return False
    return math.isfinite(scaled) and abs(scaled - round(scaled)) < 1e-6


def judge(fn) -> tuple[bool, str]:
    """Roda o candidato no dataset adversarial e decide `correct`."""
    got = fn(str(data(GATE_FILE)))
    expected = truth()

    if not isinstance(got, dict):
        return False, f"transform() deve devolver dict, devolveu {type(got).__name__}"
    if set(got) != set(expected):
        missing = sorted(set(expected) - set(got))
        extra = sorted(set(got) - set(expected))
        detail = f"chaves divergentes (faltam {len(missing)}, sobram {len(extra)})"
        if missing:
            detail += f"; primeira faltando: {missing[0]!r}"
        if extra:
            detail += f"; primeira sobrando: {extra[0]!r}"
        return False, detail

    for key in sorted(expected):
        exp, row = expected[key], got[key]
        if not isinstance(row, dict):
            return False, f"{key}: esperado dict, obtido {type(row).__name__}"
        for field in ("n", "last_ts"):
            if field not in row:
                return False, f"{key}.{field}: ausente"
            if row[field] != exp[field]:
                return False, f"{key}.{field}: esperado {exp[field]}, obtido {row[field]!r}"
        for field in ("gross", "net"):
            if field not in row:
                return False, f"{key}.{field}: ausente"
            value = row[field]
            if not _is_two_decimals(value):
                return False, (
                    f"{key}.{field}: {value!r} não é um valor de 2 casas — "
                    "o contrato exige arredondar no final"
                )
            delta = abs(float(value) - exp[field])
            if not math.isfinite(delta) or delta > exp["tol"]:
                return False, (
                    f"{key}.{field}: soma verdadeira {exp[field]:.6f}, obtido {value!r} "
                    f"(erro {delta:.4f} > tolerância {exp['tol']:.4f}). Arredondar durante a "
                    "acumulação em vez de no final produz exatamente este desvio."
                )
    return True, "ok"


GATE = evalkit.Gate(judge=judge, description="dataset adversarial, valor + apresentação")


def fingerprint(result) -> str:
    return contracts.canon_hash(
        result, fields=("n", "gross", "net", "last_ts"), places={"gross": 2, "net": 2}
    )[:16]


# ------------------------------------------------------------------- mutantes


def _mut_incremental_round(path):
    """Arredonda a cada acumulação. O atalho mais plausível — e o que furou o gate antigo."""
    agg = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            k = r["account"] + "|" + r["ccy"]
            a = agg.setdefault(k, {"n": 0, "gross": 0.0, "net": 0.0, "last_ts": 0})
            a["n"] += 1
            a["gross"] = round(a["gross"] + r["amount"], 2)
            if r["status"] == "settled":
                a["net"] = round(a["net"] + r["amount"], 2)
            a["last_ts"] = max(a["last_ts"], r["ts"])
    return agg


def _mut_no_status_filter(path):
    """Esquece o filtro de status: net vira gross."""
    out = reference(path)
    for v in out.values():
        v["net"] = v["gross"]
    return out


def _mut_pending_counts(path):
    """Lê 'liquidado' como 'não cancelado' e soma pending em net."""
    agg = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            k = r["account"] + "|" + r["ccy"]
            a = agg.setdefault(k, {"n": 0, "gross": [], "net": [], "last_ts": 0})
            a["n"] += 1
            a["gross"].append(r["amount"])
            if r["status"] != "void":
                a["net"].append(r["amount"])
            a["last_ts"] = max(a["last_ts"], r["ts"])
    return {
        k: {
            "n": a["n"],
            "gross": round(math.fsum(a["gross"]), 2),
            "net": round(math.fsum(a["net"]), 2),
            "last_ts": a["last_ts"],
        }
        for k, a in agg.items()
    }


def _mut_n_counts_only_settled(path):
    """Conta só as linhas liquidadas em n."""
    out = {}
    counts = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            if r["status"] == "settled":
                k = r["account"] + "|" + r["ccy"]
                counts[k] = counts.get(k, 0) + 1
    for k, v in reference(path).items():
        out[k] = dict(v, n=counts.get(k, 0))
    return out


def _mut_last_ts_off(path):
    """Erro de um no last_ts — o clássico de comparação estrita trocada."""
    out = reference(path)
    for v in out.values():
        v["last_ts"] -= 1
    return out


def _mut_drop_key(path):
    """Perde um grupo. Uma linha a menos num filtro faz isso."""
    out = reference(path)
    out.pop(next(iter(out)))
    return out


def _mut_group_by_account_only(path):
    """Ignora a moeda na chave — agregação plausível, contrato errado."""
    out = {}
    for k, v in reference(path).items():
        account = k.split("|")[0]
        out[account + "|BRL"] = v
    return out


def _mut_float32(path):
    """Troca precisão por velocidade. float32 tem eps ~8.0 na magnitude dos notionais."""
    import struct

    out = reference(path)
    for v in out.values():
        v["gross"] = round(struct.unpack("f", struct.pack("f", v["gross"]))[0], 2)
    return out


def _mut_unrounded(path):
    """Devolve a soma crua. Viola a apresentação, ainda que o valor esteja certo."""
    out = reference(path)
    for v in out.values():
        v["gross"] = v["gross"] + 1e-4
    return out


MUTANTS = evalkit.MutantSuite(
    reference=reference,
    mutants=[
        ("incremental_round", _mut_incremental_round),
        ("no_status_filter", _mut_no_status_filter),
        ("pending_conta_em_net", _mut_pending_counts),
        ("n_so_conta_settled", _mut_n_counts_only_settled),
        ("last_ts_off_by_one", _mut_last_ts_off),
        ("drop_one_key", _mut_drop_key),
        ("agrupa_so_por_conta", _mut_group_by_account_only),
        ("float32_precision", _mut_float32),
        ("valor_nao_arredondado", _mut_unrounded),
    ],
)


# ------------------------------------------------------------------- regimes


REGIME_FILES = (
    ("wide", "perf_wide.jsonl", "muitos grupos pequenos"),
    ("narrow", "perf_narrow.jsonl", "poucos grupos grandes"),
    ("skew", "perf_skew.jsonl", "volume concentrado"),
)


def regimes(alias_dir: str | None = None) -> list[evalkit.Regime]:
    """Os tres regimes. Com `alias_dir`, cada execucao recebe um caminho NOVO.

    O caminho novo nao e capricho: um candidato que memoiza a saida indexada
    pelo caminho devolve o resultado certo instantaneamente da segunda chamada
    em diante, passa no gate porque o resultado esta correto, e marca um score
    milhares de vezes maior sem ter otimizado coisa alguma. Trocar o caminho a
    cada execucao faz o cache errar.
    """
    out = []
    for name, filename, description in REGIME_FILES:
        path = str(data(filename))
        if alias_dir is None:
            out.append(evalkit.Regime(name, (path,), description))
        else:
            out.append(
                evalkit.Regime(
                    name,
                    (path,),
                    description,
                    args_factory=lambda p=path: (evalkit.unique_alias(p, alias_dir),),
                )
            )
    return out


def regime_floors() -> dict[str, float]:
    """O custo de so ler cada arquivo de entrada: o piso fisico do trabalho."""
    return {name: evalkit.read_floor([data(filename)]) for name, filename, _ in REGIME_FILES}


# ----------------------------------------------------------------------- main


def main() -> int:
    args = evalkit.standard_parser(__doc__.splitlines()[0]).parse_args()

    ok_data, detail = datakit.verify_lock(HERE)
    if not ok_data:
        if args.selftest:
            print(f"dataset: {detail}", file=sys.stderr)
            return 1
        evalkit.emit_failure(f"dataset inválido: {detail}")
        return 0

    if args.selftest:
        return 0 if MUTANTS.selftest(GATE) else 1

    if args.budget:
        # Mede o SEED, não a referência: é o seed que o agente paga no passo 1,
        # e dimensionar pelo candidato rápido foi precisamente a Falha 2.
        seed_fn = contracts.as_callable(
            evalkit.load_module(HERE / "seed" / ENTRYPOINT, "seedmod"), SYMBOL
        )
        seed_run = evalkit.measure(seed_fn, regimes(), repeats=3, warmup=1)
        fast_run = evalkit.measure(reference, regimes(), repeats=3, warmup=1)
        healthy, message = evalkit.budget_report(seed_run.wall_s, min(fast_run.per_regime.values()))
        print(message)
        print(f"  seed:       {seed_run.notes()}")
        print(f"  referência: {fast_run.notes()}")
        return 0 if healthy else 1

    if args.baselines:
        measurement = evalkit.measure(reference, regimes(), repeats=3, warmup=1)
        evalkit.emit_baselines({"referencia_passe_unico": measurement.throughput()})
        return 0

    candidate = evalkit.candidate_path(args.workdir, ENTRYPOINT)
    if not candidate.exists():
        evalkit.emit_failure(f"{ENTRYPOINT} ausente em {args.workdir}")
        return 0

    ok_imports, detail = contracts.stdlib_only(str(candidate))
    if not ok_imports:
        evalkit.emit_failure(detail)
        return 0

    try:
        module = evalkit.load_module(candidate)
        fn = contracts.as_callable(module, SYMBOL)
    except Exception as exc:  # noqa: BLE001
        evalkit.emit_failure(f"{type(exc).__name__}: {exc}")
        return 0

    ok_gate, detail = GATE.check(fn)
    if not ok_gate:
        evalkit.emit_failure(f"gate: {detail}")
        return 0

    # Modulo novo a cada execucao: nenhum cache de modulo sobrevive entre
    # chamadas, entao memoizar a saida deixa de pagar. Caminho novo a cada
    # execucao pelo mesmo motivo, uma camada acima.
    def fresh():
        return contracts.as_callable(evalkit.load_module(candidate, "cand_timed"), SYMBOL)

    with tempfile.TemporaryDirectory(prefix="etl_agg-alias-") as alias_dir:
        try:
            measurement = evalkit.measure(
                fn, regimes(alias_dir), repeats=5, warmup=1, fn_factory=fresh
            )
        except Exception as exc:  # noqa: BLE001
            evalkit.emit_failure(f"falhou durante a medição: {type(exc).__name__}: {exc}")
            return 0

    suspect, detail = evalkit.implausible_speed(measurement.per_regime, regime_floors())
    if suspect:
        evalkit.emit_failure(f"velocidade implausível: {detail}")
        return 0

    digest = fingerprint(fn(str(data(GATE_FILE))))
    evalkit.emit_success(
        measurement.throughput(),
        notes=f"gate=ok fingerprint={digest} {measurement.notes()}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
