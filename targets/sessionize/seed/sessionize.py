"""Sessionizacao de eventos — x_0.

CONTRATO (a verdade completa esta em kb/00-contrato.md):

    sessionize(path) -> dict[str, dict]

    chave : "<user_id>|<indice>", indice comecando em 0 por USUARIO e crescendo
            em ordem cronologica.
    valor : {"n": int, "inicio": int, "fim": int,
             "paginas": int, "duracao_ms": int}

    n            eventos da sessao
    inicio/fim   menor e maior ts da sessao
    paginas      quantidade de paginas DISTINTAS visitadas na sessao
    duracao_ms   soma de duration_ms dos eventos da sessao

    Uma sessao termina quando o intervalo ate o proximo evento do MESMO usuario
    e MAIOR que 1800 segundos. Exatamente 1800 mantem a sessao aberta.

    O arquivo vem embaralhado. A ordem de leitura nao ajuda.

Somente a biblioteca padrao.

Esta implementacao esta correta e e deliberadamente ingenua: materializa todos
os eventos, materializa de novo uma lista de registros COMPLETOS por usuario, e
ordena essas listas de dicionarios inteiros — carregando dez campos por evento
quando a sessionizacao precisa de quatro.
"""

import json


def sessionize(path):
    eventos = []
    with open(path) as fh:
        for linha in fh:
            eventos.append(json.loads(linha))

    por_usuario = {}
    for evento in eventos:
        uid = evento["user_id"]
        if uid not in por_usuario:
            por_usuario[uid] = []
        por_usuario[uid].append(evento)

    saida = {}
    for uid in por_usuario:
        do_usuario = sorted(por_usuario[uid], key=lambda e: e["ts"])
        indice = 0
        inicio = do_usuario[0]["ts"]
        anterior = do_usuario[0]["ts"]
        n = 0
        paginas = []
        duracao = 0
        for evento in do_usuario:
            ts = evento["ts"]
            if ts - anterior > 1800:
                distintas = []
                for p in paginas:
                    if p not in distintas:
                        distintas.append(p)
                saida[uid + "|" + str(indice)] = {
                    "n": n,
                    "inicio": inicio,
                    "fim": anterior,
                    "paginas": len(distintas),
                    "duracao_ms": duracao,
                }
                indice += 1
                inicio = ts
                n = 0
                paginas = []
                duracao = 0
            anterior = ts
            n += 1
            paginas.append(evento["page"])
            duracao += evento["duration_ms"]
        distintas = []
        for p in paginas:
            if p not in distintas:
                distintas.append(p)
        saida[uid + "|" + str(indice)] = {
            "n": n,
            "inicio": inicio,
            "fim": anterior,
            "paginas": len(distintas),
            "duracao_ms": duracao,
        }
    return saida
