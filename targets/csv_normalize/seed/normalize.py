"""Normalização de cadastro legado: CSV sujo -> registros canônicos — x_0.

CONTRATO (a verdade completa está em kb/00-contrato.md):

    normalize(path) -> dict[str, dict]

    chave : documento canônico — só dígitos, 11 (CPF) ou 14 (CNPJ) posições,
            preenchido com zeros à esquerda. Ex.: "00012345678"
    valor : {"n": int, "nulos": int, "invalidos": int,
             "nome": str, "uf": str|None, "data": str|None, "valor": float|None}

    n          linhas do arquivo que caíram nesta chave, antes da deduplicação
    nulos      quantas delas tinham `valor` numa sentinela de nulo declarada
    invalidos  quantas tinham `valor` com texto que não é número nem sentinela
    nome       texto normalizado da linha VENCEDORA
    uf         sigla de duas letras da linha vencedora, resolvida por tabela
    data       data ISO da linha vencedora, ou None
    valor      número da linha vencedora arredondado a 2 casas, ou None

    Vencedora é a linha de data mais recente; sem data perde para com data; no
    empate vence a que aparece por último no arquivo.

Somente a biblioteca padrão. A ordem das chaves no dict de saída não importa.

Esta implementação está correta e é deliberadamente ingênua: ela materializa
todas as linhas como dicionários, materializa uma segunda lista de registros
normalizados, agrupa numa terceira estrutura e só então percorre cada grupo mais
duas vezes — uma para achar o vencedor e outra para contar. Compila as mesmas
expressões regulares dentro do laço e descobre o formato de data tentando três
`strptime` até um não levantar exceção. É o código que sai naturalmente de
escrever o contrato de cima para baixo, e é o ponto de partida da busca.
"""

import csv
import re
import unicodedata
from datetime import datetime

SENTINELAS = ["", "NULL", "N/A", "NA", "NONE", "NIL", "-", "--"]
LARGURA_ZERO = ["\u200b", "\u200c", "\u200d", "\ufeff"]
FORMATOS = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%y"]

OK = 0
NULO = 1
INVALIDO = 2

ESTADOS = [
    ("AC", "Acre"),
    ("AL", "Alagoas"),
    ("AP", "Amapá"),
    ("AM", "Amazonas"),
    ("BA", "Bahia"),
    ("CE", "Ceará"),
    ("DF", "Distrito Federal"),
    ("ES", "Espírito Santo"),
    ("GO", "Goiás"),
    ("MA", "Maranhão"),
    ("MT", "Mato Grosso"),
    ("MS", "Mato Grosso do Sul"),
    ("MG", "Minas Gerais"),
    ("PA", "Pará"),
    ("PB", "Paraíba"),
    ("PR", "Paraná"),
    ("PE", "Pernambuco"),
    ("PI", "Piauí"),
    ("RJ", "Rio de Janeiro"),
    ("RN", "Rio Grande do Norte"),
    ("RS", "Rio Grande do Sul"),
    ("RO", "Rondônia"),
    ("RR", "Roraima"),
    ("SC", "Santa Catarina"),
    ("SP", "São Paulo"),
    ("SE", "Sergipe"),
    ("TO", "Tocantins"),
]


def tirar_largura_zero(bruto):
    texto = bruto
    for caractere in LARGURA_ZERO:
        texto = texto.replace(caractere, "")
    return texto


def normalizar_texto(bruto):
    texto = unicodedata.normalize("NFC", bruto)
    texto = tirar_largura_zero(texto)
    espacos = re.compile(r"\s+")
    texto = espacos.sub(" ", texto)
    return texto.strip().upper()


def tirar_acentos(bruto):
    decomposto = unicodedata.normalize("NFD", bruto)
    resultado = ""
    for caractere in decomposto:
        if unicodedata.combining(caractere) == 0:
            resultado = resultado + caractere
    return resultado


def normalizar_uf(bruto):
    texto = normalizar_texto(bruto)
    if texto == "" or texto in SENTINELAS:
        return None
    chave = tirar_acentos(texto)
    for sigla, nome in ESTADOS:
        if chave == sigla:
            return sigla
        if chave == tirar_acentos(nome).upper():
            return sigla
    return None


def normalizar_documento(bruto):
    nao_digito = re.compile(r"[^0-9]")
    digitos = nao_digito.sub("", bruto)
    if len(digitos) == 0 or len(digitos) > 14:
        return None
    if len(digitos) <= 11:
        return digitos.rjust(11, "0")
    return digitos.rjust(14, "0")


def normalizar_data(bruto):
    texto = tirar_largura_zero(bruto).strip()
    if texto == "" or texto.upper() in SENTINELAS:
        return None
    for formato in FORMATOS:
        try:
            momento = datetime.strptime(texto, formato)
        except ValueError:
            continue
        return "%04d-%02d-%02d" % (momento.year, momento.month, momento.day)
    return None


def normalizar_valor(bruto):
    texto = tirar_largura_zero(bruto).strip()
    if texto == "" or texto.upper() in SENTINELAS:
        return None, NULO

    negativo = False
    if len(texto) > 1 and texto.startswith("(") and texto.endswith(")"):
        negativo = True
        texto = texto[1:-1].strip()

    tem_sinal = False
    tem_moeda = False
    for _ in range(2):
        if not tem_sinal and (texto.startswith("+") or texto.startswith("-")):
            if texto.startswith("-"):
                negativo = not negativo
            tem_sinal = True
            texto = texto[1:].strip()
        elif not tem_moeda and texto[:2].upper() == "R$":
            tem_moeda = True
            texto = texto[2:].strip()
        elif not tem_moeda and texto.startswith("$"):
            tem_moeda = True
            texto = texto[1:].strip()
        else:
            break

    so_numero = re.compile(r"[0-9.,]+")
    if texto == "" or so_numero.fullmatch(texto) is None:
        return None, INVALIDO

    ultimo_ponto = texto.rfind(".")
    ultima_virgula = texto.rfind(",")
    if ultimo_ponto >= 0 and ultima_virgula >= 0:
        if ultimo_ponto > ultima_virgula:
            corte = ultimo_ponto
        else:
            corte = ultima_virgula
    elif ultimo_ponto >= 0:
        corte = ultimo_ponto
        if texto.count(".") > 1 or len(texto) - corte - 1 == 3:
            corte = -1
    elif ultima_virgula >= 0:
        corte = ultima_virgula
        if texto.count(",") > 1 or len(texto) - corte - 1 == 3:
            corte = -1
    else:
        corte = -1

    if corte < 0:
        parte_inteira = texto
        parte_fracao = ""
    else:
        parte_inteira = texto[:corte]
        parte_fracao = texto[corte + 1 :]

    digitos = parte_inteira.replace(".", "").replace(",", "")
    if digitos == "" and parte_fracao == "":
        return None, INVALIDO
    if digitos != "" and not digitos.isdigit():
        return None, INVALIDO
    if parte_fracao != "" and not parte_fracao.isdigit():
        return None, INVALIDO
    if digitos == "":
        digitos = "0"
    if parte_fracao == "":
        parte_fracao = "0"

    numero = float(digitos + "." + parte_fracao)
    if negativo:
        numero = -numero
    return round(numero, 2), OK


def normalize(path):
    linhas = []
    with open(path, newline="", encoding="utf-8-sig") as arquivo:
        leitor = csv.DictReader(arquivo)
        for linha in leitor:
            linhas.append(linha)

    registros = []
    for linha in linhas:
        chave = normalizar_documento(linha["doc"])
        if chave is None:
            continue
        registros.append(
            {
                "chave": chave,
                "nome": normalizar_texto(linha["nome"]),
                "uf": normalizar_uf(linha["uf"]),
                "data": normalizar_data(linha["data_ref"]),
                "valor": normalizar_valor(linha["valor"]),
            }
        )

    grupos = {}
    for registro in registros:
        if registro["chave"] not in grupos:
            grupos[registro["chave"]] = []
        grupos[registro["chave"]].append(registro)

    saida = {}
    for chave in grupos:
        grupo = grupos[chave]

        vencedor = grupo[0]
        for registro in grupo:
            if (registro["data"] or "") >= (vencedor["data"] or ""):
                vencedor = registro

        nulos = 0
        invalidos = 0
        for registro in grupo:
            if registro["valor"][1] == NULO:
                nulos = nulos + 1
            elif registro["valor"][1] == INVALIDO:
                invalidos = invalidos + 1

        saida[chave] = {
            "n": len(grupo),
            "nulos": nulos,
            "invalidos": invalidos,
            "nome": vencedor["nome"],
            "uf": vencedor["uf"],
            "data": vencedor["data"],
            "valor": vencedor["valor"][0],
        }
    return saida
