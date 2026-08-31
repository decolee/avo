"""Agregacao por (account, ccy) — extracao dirigida, sem chamada por campo.

Mesma estrategia da v2. A mudanca e de forma, nao de algoritmo: a funcao
auxiliar `_field` era chamada cinco vezes por linha, e chamada de funcao em
Python custa mais que o trabalho que ela fazia. Aqui a busca esta inline e o
espaco depois dos dois-pontos entra no proprio literal procurado, o que elimina
tambem o laco de pular espaco.

A suposicao declarada continua a mesma da v2: cada chave aparece uma vez por
linha, e `account`, `ccy` e `status` sao tokens sem escape.
"""
import json

_ACCOUNT = '"account": "'
_CCY = '"ccy": "'
_AMOUNT = '"amount": '
_TS = '"ts": '
_STATUS = '"status": "'


def transform(path):
    agg = {}
    get = agg.get
    find = str.find
    with open(path) as fh:
        for line in fh:
            i = find(line, _ACCOUNT) + 12
            j = find(line, '"', i)
            account = line[i:j]

            i = find(line, _CCY, j) + 8
            j = find(line, '"', i)
            key = account + "|" + line[i:j]

            i = find(line, _AMOUNT, j) + 10
            j = find(line, ",", i)
            amount = float(line[i:j])

            i = find(line, _TS, j) + 6
            j = find(line, ",", i)
            ts = int(line[i:j])

            i = find(line, _STATUS, j) + 11
            j = find(line, '"', i)
            settled = line[i:j] == "settled"

            acc = get(key)
            if acc is None:
                agg[key] = acc = [0, 0.0, 0.0, 0]
                get = agg.get
            acc[0] += 1
            acc[1] += amount
            if settled:
                acc[2] += amount
            if ts > acc[3]:
                acc[3] = ts

    if not agg:
        json.loads("{}")
    return {
        k: {"n": a[0], "gross": round(a[1], 2), "net": round(a[2], 2), "last_ts": a[3]}
        for k, a in agg.items()
    }
