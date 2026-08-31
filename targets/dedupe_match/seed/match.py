"""Deduplicacao de cadastro — x_0.

CONTRATO (a verdade completa esta em kb/00-contrato.md):

    match(records: list[dict]) -> iteravel de pares (id_a, id_b)

    Cada registro tem: id, nome, cidade, uf, telefone, email, documento,
    nascimento, endereco. Todos sao str; campo ausente vem como "".

    Devolva os pares de ids que sao a MESMA entidade. A ordem dentro do par nao
    importa e a ordem dos pares tambem nao. Cada par uma vez so.

Somente a biblioteca padrao. `match` e uma funcao pura sobre os registros que
recebe: nao le arquivo, nao escreve arquivo, e nao pode depender da ordem em
que os registros chegaram.

O score e F1 em tres bancos, sob um ORCAMENTO DE TEMPO somado. Estourar o
orcamento vale zero, entao ficar melhor comeca por ficar mais barato.

Esta implementacao esta correta — respeita o contrato — e e deliberadamente
fraca das duas maneiras ao mesmo tempo:

  Ela ACHA POUCO. Duas grafias do mesmo nome ("José da Silva" e "JOSE SILVA")
  nao sao a mesma string, entao a duplicata passa batido.

  Ela ERRA MUITO. Dois homonimos na mesma cidade tem a mesma string, entao
  viram duplicata mesmo tendo data de nascimento e telefone diferentes.

E ela gasta a maior parte do orcamento para conseguir isso: compara todos os
pares e normaliza os dois nomes DENTRO do laco, refazendo o mesmo trabalho
n vezes por registro.
"""


def _normalizar(texto):
    return " ".join(texto.lower().split())


def match(records):
    pares = []
    n = len(records)
    for i in range(n):
        a = records[i]
        for j in range(i + 1, n):
            b = records[j]
            nome_a = _normalizar(a["nome"])
            nome_b = _normalizar(b["nome"])
            if nome_a and nome_a == nome_b:
                x, y = a["id"], b["id"]
                pares.append((x, y) if x <= y else (y, x))
    return pares
