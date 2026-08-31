"""Agregação de transações por (account, ccy) — x_0.

CONTRATO (a verdade completa está em kb/00-contrato.md):

    transform(path) -> dict[str, dict]

    chave : "ACC00001|BRL"   ou seja  f"{account}|{ccy}"
    valor : {"n": int, "gross": float, "net": float, "last_ts": int}

    n        contagem de TODAS as linhas do grupo
    gross    soma de amount de todas as linhas, arredondada a 2 casas NO FINAL
    net      soma de amount apenas de status == "settled", idem
    last_ts  maior ts do grupo

Somente a biblioteca padrão. A ordem das chaves no dict de saída não importa.

Esta implementação está correta e é deliberadamente ingênua: ela materializa
todas as linhas, depois materializa uma lista por grupo, e então percorre cada
grupo quatro vezes — uma por campo. É o código que sai naturalmente de escrever
o contrato direto, e é o ponto de partida da busca.
"""

import json


def transform(path):
    rows = []
    with open(path) as fh:
        for line in fh:
            rows.append(json.loads(line))

    groups = {}
    for row in rows:
        key = row["account"] + "|" + row["ccy"]
        if key not in groups:
            groups[key] = []
        groups[key].append(row)

    out = {}
    for key in groups:
        group = groups[key]
        out[key] = {
            "n": len(group),
            "gross": round(sum(r["amount"] for r in group), 2),
            "net": round(sum(r["amount"] for r in group if r["status"] == "settled"), 2),
            "last_ts": max(r["ts"] for r in group),
        }
    return out
