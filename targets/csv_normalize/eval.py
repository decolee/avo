"""f(x) do target csv_normalize — o árbitro. Nunca afrouxe isto para um candidato passar.

Separação deliberada entre gate e benchmark:

  CORREÇÃO    -> data/gate_adv.csv. Pequeno, escrito à mão, adversarial em cada
                 linha: BOM, CRLF misturado com LF, vírgula e quebra de linha
                 dentro de campo citado, aspas duplicadas, acento combinante,
                 espaço não-quebrável, largura zero, data ambígua, decimal nos
                 dois formatos, negativo em parênteses, todas as sentinelas de
                 nulo e duplicatas que exercitam o desempate. É o ÚNICO dataset
                 que decide `correct`.
  PERFORMANCE -> data/perf_*.csv. Grandes, regulares, três formas de dado.
                 Só medem tempo.

Por que a separação importa aqui em particular: normalização é o domínio onde o
atalho rápido e o atalho errado são o *mesmo* atalho. `linha.split(",")` é ~10x
mais rápido que o módulo `csv` e funciona perfeitamente enquanto nenhum campo
tiver vírgula citada. Se o gate rodasse nos dados de performance — que são
regulares por construção, porque precisam ser grandes — ele aprovaria esse
atalho e a busca inteira convergiria para código que quebra no primeiro arquivo
real. O gate roda num arquivo que existe exatamente para punir suposições sobre
a forma do arquivo.

COMO A CORREÇÃO É DECIDIDA.

Campo a campo, com o rigor que cada tipo merece:

  `n`, `nulos`, `invalidos`  igualdade exata. São contagens; não há tolerância
                             razoável para uma contagem errada.
  `nome`, `uf`, `data`       igualdade exata de string. A normalização é
                             determinística e o contrato declara o resultado
                             caractere a caractere. Quando divergem, o
                             diagnóstico mostra os codepoints em `ascii()` —
                             senão "JOSÉ != JOSÉ" na tela é indistinguível de
                             um bug do terminal, e a diferença NFC/NFD é
                             literalmente invisível.
  `valor`                    o número tem que estar a menos de meio centavo do
                             valor verdadeiro (não arredondado) E ser de fato
                             um valor de duas casas. Duas checagens porque elas
                             pegam coisas opostas: a primeira pega quem parseou
                             errado, a segunda pega quem não arredondou. `None`
                             só casa com `None`: um valor ausente e um valor
                             zero são fatos diferentes sobre o mundo.

O hash canônico continua sendo calculado e aparece em `notes` como impressão
digital — útil para ver de relance que duas versões produzem a mesma saída —
mas não é ele que decide. Hash é bom para comparar, ruim para diagnosticar.
"""

from __future__ import annotations

import atexit
import csv
import re
import sys
import tempfile
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from labkit import contracts, datakit, evalkit  # noqa: E402

ENTRYPOINT = "normalize.py"
SYMBOL = "normalize"

PERF_FILES = ("perf_limpo.csv", "perf_sujo.csv", "perf_dup.csv")
GATE_FILE = "gate_adv.csv"

#: As cinco colunas que a transformação consome. O arquivo tem dezoito; a folga
#: é parte do problema, e a ORDEM delas muda entre arquivos de propósito.
COLUNAS = ("doc", "nome", "uf", "data_ref", "valor")

#: Meio centavo: o máximo que um arredondamento correto a 2 casas pode afastar
#: o valor apresentado do valor verdadeiro lido do arquivo.
MEIO_CENTAVO = 0.005 + 1e-9

#: Classes que `_valor` devolve junto com o número. `NULO` é uma sentinela
#: declarada ("NULL", "-", vazio); `INVALIDO` é texto que deveria ser número e
#: não é. Os dois viram `valor=None`, mas contam em campos diferentes — é essa
#: distinção que dá ao gate como perceber quem trata "-" como lixo.
OK, NULO, INVALIDO = 0, 1, 2


def data(name: str) -> Path:
    return datakit.data_dir(HERE) / name


# ------------------------------------------------- primitivas de normalização
#
# Estas cinco funções SÃO o contrato executável. `kb/00-contrato.md` descreve o
# mesmo comportamento em prosa; se algum dia divergirem, este arquivo é a
# verdade. Cada mutante troca exatamente uma delas — é o que torna o selftest
# um experimento controlado em vez de doze programas diferentes.

#: Caracteres de largura zero: lixo invisível que sobra de export de planilha e
#: de copiar/colar de web. Não são espaço (`str.isspace()` é falso), então
#: `split()` não os toca; ficam grudados no meio da palavra e destroem qualquer
#: comparação de igualdade. São REMOVIDOS, não trocados por espaço.
_LARGURA_ZERO = {0x200B: None, 0x200C: None, 0x200D: None, 0xFEFF: None}

_NAO_DIGITO = re.compile(r"[^0-9]")
_SO_NUMERO = re.compile(r"[0-9.,]+")

#: Sentinelas de nulo, comparadas em caixa alta depois do strip.
_SENTINELAS = frozenset(("", "NULL", "N/A", "NA", "NONE", "NIL", "-", "--"))

_DIAS_NO_MES = (0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def _doc(bruto: str) -> str | None:
    """Documento -> chave canônica. `None` quando a linha não tem chave usável."""
    digitos = _NAO_DIGITO.sub("", bruto)
    largura = len(digitos)
    if largura == 0 or largura > 14:
        return None
    return digitos.rjust(11, "0") if largura <= 11 else digitos.rjust(14, "0")


def _texto(bruto: str) -> str:
    """NFC, remove largura zero, colapsa espaço, tira das pontas, caixa alta.

    `" ".join(s.split())` faz três coisas de uma vez: quebra em qualquer run de
    espaço Unicode (inclusive `\\xa0` e a quebra de linha que veio de dentro de
    um campo citado), colapsa o run em um único espaço e descarta as pontas.
    """
    s = unicodedata.normalize("NFC", bruto).translate(_LARGURA_ZERO)
    return " ".join(s.split()).upper()


#: As 27 unidades federativas, sigla e nome. A tabela existe porque o campo `uf`
#: de um cadastro legado vem ora como sigla, ora como nome por extenso, e as duas
#: formas se referem à mesma coisa.
ESTADOS = (
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
)


def _sem_acento(texto: str) -> str:
    """Descarta os diacríticos combinantes. `SÃO PAULO` e `SAO PAULO` viram um só.

    A regra é geral de propósito — decompõe e joga fora a categoria combinante —
    e não uma tabela dos acentos que este arquivo por acaso contém. O atalho da
    tabela é tentador e funciona até o dia em que chega um trema.
    """
    if texto.isascii():
        return texto
    return "".join(c for c in unicodedata.normalize("NFD", texto) if not unicodedata.combining(c))


#: Índice pronto: sigla e nome sem acento apontam para a mesma sigla.
_UF_POR_CHAVE = {sigla: sigla for sigla, _ in ESTADOS}
_UF_POR_CHAVE.update({_sem_acento(nome).upper(): sigla for sigla, nome in ESTADOS})


def _uf(bruto: str, desconhecida_e_none: bool = True) -> str | None:
    """Sigla, nome por extenso ou lixo -> sigla canônica de duas letras, ou `None`."""
    texto = _texto(bruto)
    if not texto or texto in _SENTINELAS:
        return None
    sigla = _UF_POR_CHAVE.get(_sem_acento(texto))
    if sigla is None and not desconhecida_e_none:
        return texto
    return sigla


def _valido_no_calendario(ano: int, mes: int, dia: int) -> bool:
    if mes < 1 or mes > 12 or dia < 1 or ano < 1 or ano > 9999:
        return False
    limite = _DIAS_NO_MES[mes]
    if mes == 2 and ano % 4 == 0 and (ano % 100 != 0 or ano % 400 == 0):
        limite = 29
    return dia <= limite


def _ano_de_dois_digitos(aa: int) -> int:
    """Janela POSIX, a mesma que `%y` do `strptime` usa: 00-68 é 20xx, 69-99 é 19xx."""
    return 2000 + aa if aa <= 68 else 1900 + aa


def _data(bruto: str, janela=_ano_de_dois_digitos, dia_primeiro: bool = True) -> str | None:
    """Data em três formatos de largura fixa -> ISO. Qualquer outra coisa é `None`."""
    s = bruto.translate(_LARGURA_ZERO).strip()
    if not s or s.upper() in _SENTINELAS:
        return None
    tamanho = len(s)
    try:
        if tamanho == 10 and s[4] == "-" and s[7] == "-":
            ano, mes, dia = int(s[0:4]), int(s[5:7]), int(s[8:10])
        elif tamanho == 10 and s[2] == "/" and s[5] == "/":
            primeiro, segundo, ano = int(s[0:2]), int(s[3:5]), int(s[6:10])
            dia, mes = (primeiro, segundo) if dia_primeiro else (segundo, primeiro)
        elif tamanho == 8 and s[2] == "-" and s[5] == "-":
            primeiro, segundo, aa = int(s[0:2]), int(s[3:5]), int(s[6:8])
            dia, mes = (primeiro, segundo) if dia_primeiro else (segundo, primeiro)
            ano = janela(aa)
        else:
            return None
    except ValueError:
        return None
    if not _valido_no_calendario(ano, mes, dia):
        return None
    return f"{ano:04d}-{mes:02d}-{dia:02d}"


def _separador_decimal(corpo: str) -> int:
    """Índice do separador decimal em `corpo`, ou -1 se o número é inteiro.

    A regra inteira do laboratório em seis linhas. Ela é heurística porque a
    fonte é ambígua — `1.500` pode ser mil e quinhentos ou um e meio — e a
    escolha foi ser determinística, não adivinhar: quando só um separador
    aparece uma única vez, três dígitos depois dele significam milhar.
    """
    ponto, virgula = corpo.rfind("."), corpo.rfind(",")
    if ponto >= 0 and virgula >= 0:
        return ponto if ponto > virgula else virgula
    corte = ponto if ponto >= 0 else virgula
    if corte < 0:
        return -1
    if corpo.count(corpo[corte]) > 1 or len(corpo) - corte - 1 == 3:
        return -1
    return corte


#: Sentinelas menos o traço, para o mutante que trata "-" como lixo em vez de nulo.
_SENTINELAS_SEM_TRACO = _SENTINELAS - {"-", "--"}


def _valor(
    bruto: str,
    negativo_no_parenteses: bool = True,
    traco_e_sentinela: bool = True,
    arredondar: bool = True,
):
    """Texto monetário -> `(float | None, classe)`.

    A gramática aceita, nesta ordem de casca para dentro: parênteses (que
    negam), depois — em qualquer ordem, no máximo uma vez cada — um sinal e um
    prefixo de moeda, e por fim `[0-9.,]+`.

    `arredondar=False` devolve o número lido sem o `round` final. É contra esse
    número que o gate mede a tolerância de meio centavo: arredondar antes de
    comparar esconderia justamente o erro que se quer ver.
    """
    s = bruto.translate(_LARGURA_ZERO).strip()
    sentinelas = _SENTINELAS if traco_e_sentinela else _SENTINELAS_SEM_TRACO
    if not s or s.upper() in sentinelas:
        return None, NULO

    negativo = False
    if len(s) > 1 and s[0] == "(" and s[-1] == ")":
        negativo = negativo_no_parenteses
        s = s[1:-1].strip()

    tem_sinal = tem_moeda = False
    for _ in range(2):
        if not tem_sinal and s[:1] in ("+", "-"):
            negativo ^= s[0] == "-"
            tem_sinal, s = True, s[1:].strip()
        elif not tem_moeda and s[:2].upper() == "R$":
            tem_moeda, s = True, s[2:].strip()
        elif not tem_moeda and s[:1] == "$":
            tem_moeda, s = True, s[1:].strip()
        else:
            break

    if not s or _SO_NUMERO.fullmatch(s) is None:
        return None, INVALIDO

    corte = _separador_decimal(s)
    inteiro, fracao = (s, "") if corte < 0 else (s[:corte], s[corte + 1 :])
    digitos = inteiro.replace(".", "").replace(",", "")
    if not digitos and not fracao:
        return None, INVALIDO
    if (digitos and not digitos.isdigit()) or (fracao and not fracao.isdigit()):
        return None, INVALIDO

    x = float((digitos or "0") + "." + (fracao or "0"))
    if negativo:
        x = -x
    return (round(x, 2) if arredondar else x), OK


def _melhor(data_atual: str | None, data_nova: str | None) -> bool:
    """Desempate: data mais recente vence; empate vai para quem aparece depois.

    `None` vira `""`, que ordena antes de qualquer data ISO — então uma linha
    sem data perde para qualquer linha com data, e o `>=` (não `>`) faz o
    último do arquivo vencer o empate, porque o laço visita em ordem de arquivo.
    """
    return (data_nova or "") >= (data_atual or "")


# ------------------------------------------------------------------ pipeline


def _pipeline(
    path,
    doc_fn=_doc,
    texto_fn=_texto,
    data_fn=_data,
    valor_fn=_valor,
    melhor_fn=_melhor,
    uf_fn=_uf,
):
    """A montagem. Um passe, um dicionário, vencedor decidido na hora.

    As funções são parâmetros para que cada mutante troque UMA peça e nada mais.
    Um mutante que reescreve o programa inteiro não prova nada sobre o gate; um
    que troca só `_texto` prova que o gate vê a diferença NFC.
    """
    saida: dict[str, dict] = {}
    with open(path, newline="", encoding="utf-8-sig") as fh:
        leitor = csv.reader(fh)
        cabecalho = next(leitor, None)
        if cabecalho is None:
            return saida
        posicao = {nome: i for i, nome in enumerate(cabecalho)}
        i_doc, i_nome, i_uf, i_data, i_valor = (posicao[c] for c in COLUNAS)

        for linha in leitor:
            chave = doc_fn(linha[i_doc])
            if chave is None:
                continue
            valor, classe = valor_fn(linha[i_valor])
            data_iso = data_fn(linha[i_data])
            grupo = saida.get(chave)
            if grupo is None:
                saida[chave] = {
                    "n": 1,
                    "nulos": 1 if classe == NULO else 0,
                    "invalidos": 1 if classe == INVALIDO else 0,
                    "nome": texto_fn(linha[i_nome]),
                    "uf": uf_fn(linha[i_uf]),
                    "data": data_iso,
                    "valor": valor,
                }
                continue
            grupo["n"] += 1
            if classe == NULO:
                grupo["nulos"] += 1
            elif classe == INVALIDO:
                grupo["invalidos"] += 1
            if melhor_fn(grupo["data"], data_iso):
                grupo["nome"] = texto_fn(linha[i_nome])
                grupo["uf"] = uf_fn(linha[i_uf])
                grupo["data"] = data_iso
                grupo["valor"] = valor
    return saida


def reference(path):
    """A implementação correta, com as cinco primitivas no lugar."""
    return _pipeline(path)


# ------------------------------------------------------------------ verdade


_VERDADE: dict | None = None


def _verdade() -> dict:
    """Referência sobre o gate, mais o valor NÃO arredondado para a tolerância."""
    global _VERDADE
    if _VERDADE is None:
        alvo = str(data(GATE_FILE))
        esperado = reference(alvo)
        cru = _pipeline(alvo, valor_fn=lambda s: _valor(s, arredondar=False))
        for chave, linha in esperado.items():
            linha["valor_cru"] = cru[chave]["valor"]
        _VERDADE = esperado
    return _VERDADE


# ---------------------------------------------------------------------- gate


def _duas_casas(valor) -> bool:
    try:
        escalado = float(valor) * 100.0
    except (TypeError, ValueError):
        return False
    return abs(escalado - round(escalado)) < 1e-6


def judge(fn) -> tuple[bool, str]:
    """Roda o candidato no dataset adversarial e decide `correct`."""
    got = fn(str(data(GATE_FILE)))
    esperado = _verdade()

    if not isinstance(got, dict):
        return False, f"normalize() deve devolver dict, devolveu {type(got).__name__}"
    if set(got) != set(esperado):
        faltam = sorted(set(esperado) - set(got))
        sobram = sorted(set(got) - set(esperado))
        detalhe = f"chaves divergentes (faltam {len(faltam)}, sobram {len(sobram)})"
        if faltam:
            detalhe += f"; primeira faltando: {faltam[0]!r}"
        if sobram:
            detalhe += f"; primeira sobrando: {sobram[0]!r}"
        return False, detalhe

    for chave in sorted(esperado):
        exp, linha = esperado[chave], got[chave]
        if not isinstance(linha, dict):
            return False, f"{chave}: esperado dict, obtido {type(linha).__name__}"

        for campo in ("n", "nulos", "invalidos"):
            if campo not in linha:
                return False, f"{chave}.{campo}: ausente"
            if linha[campo] != exp[campo]:
                return False, (
                    f"{chave}.{campo}: esperado {exp[campo]}, obtido {linha[campo]!r}. "
                    "`n` conta todas as linhas da chave; `nulos` só as sentinelas "
                    "declaradas; `invalidos` o texto que deveria ser número e não é."
                )

        for campo in ("nome", "uf"):
            if campo not in linha:
                return False, f"{chave}.{campo}: ausente"
            if linha[campo] != exp[campo]:
                return False, (
                    f"{chave}.{campo}: esperado {ascii(exp[campo])}, "
                    f"obtido {ascii(linha[campo])} (codepoints em ascii() de propósito: "
                    "NFC vs NFD é invisível na tela)"
                )

        if "data" not in linha:
            return False, f"{chave}.data: ausente"
        if linha["data"] != exp["data"]:
            return False, (
                f"{chave}.data: esperado {exp['data']!r}, obtido {linha['data']!r}. "
                "Formato ambíguo é dia-primeiro; data fora do calendário é None."
            )

        if "valor" not in linha:
            return False, f"{chave}.valor: ausente"
        obtido = linha["valor"]
        if exp["valor"] is None or obtido is None:
            if exp["valor"] is not obtido:
                return False, (
                    f"{chave}.valor: esperado {exp['valor']!r}, obtido {obtido!r}. "
                    "Ausente e zero são fatos diferentes; sentinela de nulo vira None."
                )
            continue
        if not _duas_casas(obtido):
            return False, (
                f"{chave}.valor: {obtido!r} não é um valor de 2 casas — o contrato "
                "exige arredondar o número lido a 2 casas decimais."
            )
        delta = abs(float(obtido) - exp["valor_cru"])
        if not (delta <= MEIO_CENTAVO):
            return False, (
                f"{chave}.valor: valor verdadeiro {exp['valor_cru']!r}, obtido {obtido!r} "
                f"(erro {delta:.4f} > {MEIO_CENTAVO:.4f}). Confira a regra do separador "
                "decimal e o negativo entre parênteses em kb/00-contrato.md."
            )
    return True, "ok"


GATE = evalkit.Gate(judge=judge, description="dataset adversarial, campo a campo")


def fingerprint(resultado) -> str:
    return contracts.canon_hash(
        resultado,
        fields=("n", "nulos", "invalidos", "nome", "uf", "data", "valor"),
        places={"valor": 2},
    )[:16]


# ------------------------------------------------------------------ mutantes
#
# Cada um é um atalho que um otimizador de verdade tentaria, não um bug absurdo.
# Onze deles trocam uma única primitiva; dois reescrevem o laço porque o atalho
# que eles codificam É sobre o laço.


def _mut_sem_nfc(path):
    """Pula a normalização Unicode. `e`+acento combinante deixa de ser `é`."""
    return _pipeline(path, texto_fn=lambda s: " ".join(s.translate(_LARGURA_ZERO).split()).upper())


def _mut_texto_so_strip(path):
    """`strip().upper()`: tira das pontas e esquece o espaço duplo do meio."""
    return _pipeline(path, texto_fn=lambda s: unicodedata.normalize("NFC", s).strip().upper())


def _mut_texto_sem_largura_zero(path):
    """Colapsa espaço mas deixa o lixo invisível. Passa em qualquer inspeção visual."""
    return _pipeline(
        path, texto_fn=lambda s: " ".join(unicodedata.normalize("NFC", s).split()).upper()
    )


def _mut_data_mes_primeiro(path):
    """Lê `03/04/2024` como 4 de março. O erro de localidade mais caro que existe."""
    return _pipeline(path, data_fn=lambda s: _data(s, dia_primeiro=False))


def _mut_pivot_ano_50(path):
    """Move a janela de dois dígitos de 68/69 para 50. Plausível e errado."""
    return _pipeline(
        path, data_fn=lambda s: _data(s, janela=lambda aa: 2000 + aa if aa <= 50 else 1900 + aa)
    )


def _mut_decimal_sempre_br(path):
    """Assume formato brasileiro sempre: ponto é milhar, vírgula é decimal."""

    def valor(bruto):
        original, classe = _valor(bruto)
        if classe != OK:
            return original, classe
        s = bruto.translate(_LARGURA_ZERO).strip()
        negativo = s.startswith("(")
        s = s.strip("()").replace("R$", "").replace("$", "").strip()
        if s.startswith("-"):
            negativo, s = not negativo, s[1:].strip()
        s = s.replace(".", "").replace(",", ".")
        try:
            x = float(s)
        except ValueError:
            return None, INVALIDO
        return round(-x if negativo else x, 2), OK

    return _pipeline(path, valor_fn=valor)


def _mut_parenteses_positivos(path):
    """Tira os parênteses e esquece que eles significavam negativo."""
    return _pipeline(path, valor_fn=lambda s: _valor(s, negativo_no_parenteses=False))


def _mut_traco_nao_e_sentinela(path):
    """`-` vira lixo em vez de nulo: `nulos` some para `invalidos`."""
    return _pipeline(path, valor_fn=lambda s: _valor(s, traco_e_sentinela=False))


def _mut_uf_com_acento(path):
    """Compara o nome do estado sem tirar os acentos: `SÃO PAULO` deixa de casar."""

    def uf(bruto):
        texto = _texto(bruto)
        if not texto or texto in _SENTINELAS:
            return None
        return _UF_POR_CHAVE.get(texto)

    return _pipeline(path, uf_fn=uf)


def _mut_uf_desconhecida_vira_texto(path):
    """Devolve o texto cru quando não reconhece a UF, em vez de `None`."""
    return _pipeline(path, uf_fn=lambda s: _uf(s, desconhecida_e_none=False))


def _mut_dedup_primeiro_vence(path):
    """Mantém o primeiro registro da chave. `setdefault` puro faz exatamente isto."""
    return _pipeline(path, melhor_fn=lambda atual, nova: False)


def _mut_dedup_ignora_data(path):
    """Último do arquivo vence, sem olhar a data. É o `dict[k] = v` de sempre."""
    return _pipeline(path, melhor_fn=lambda atual, nova: True)


def _mut_doc_sem_padding(path):
    """Tira a pontuação mas não normaliza a largura: `1234567` != `00001234567`."""

    def doc(bruto):
        digitos = _NAO_DIGITO.sub("", bruto)
        return digitos if 0 < len(digitos) <= 14 else None

    return _pipeline(path, doc_fn=doc)


def _mut_colunas_por_posicao(path):
    """Hardcoda os índices do layout de perf em vez de ler o cabeçalho."""
    saida: dict[str, dict] = {}
    with open(path, newline="", encoding="utf-8-sig") as fh:
        leitor = csv.reader(fh)
        next(leitor, None)
        for linha in leitor:
            chave = _doc(linha[1])
            if chave is None:
                continue
            valor, classe = _valor(linha[10])
            data_iso = _data(linha[8])
            grupo = saida.get(chave)
            if grupo is None:
                saida[chave] = {
                    "n": 1,
                    "nulos": 1 if classe == NULO else 0,
                    "invalidos": 1 if classe == INVALIDO else 0,
                    "nome": _texto(linha[2]),
                    "uf": _uf(linha[7]),
                    "data": data_iso,
                    "valor": valor,
                }
                continue
            grupo["n"] += 1
            if classe == NULO:
                grupo["nulos"] += 1
            elif classe == INVALIDO:
                grupo["invalidos"] += 1
            if _melhor(grupo["data"], data_iso):
                grupo.update(nome=_texto(linha[2]), uf=_uf(linha[7]), data=data_iso, valor=valor)
    return saida


def _mut_split_por_virgula(path):
    """Troca o módulo `csv` por `split(",")`. O atalho mais rápido e mais errado."""
    saida: dict[str, dict] = {}
    with open(path, encoding="utf-8-sig") as fh:
        cabecalho = fh.readline().rstrip("\r\n").split(",")
        posicao = {nome: i for i, nome in enumerate(cabecalho)}
        i_doc, i_nome, i_uf, i_data, i_valor = (posicao[c] for c in COLUNAS)
        i_maior = max(i_doc, i_nome, i_uf, i_data, i_valor)
        for bruta in fh:
            linha = bruta.rstrip("\r\n").split(",")
            if len(linha) <= i_maior:
                continue
            chave = _doc(linha[i_doc])
            if chave is None:
                continue
            valor, classe = _valor(linha[i_valor])
            data_iso = _data(linha[i_data])
            grupo = saida.get(chave)
            if grupo is None:
                saida[chave] = {
                    "n": 1,
                    "nulos": 1 if classe == NULO else 0,
                    "invalidos": 1 if classe == INVALIDO else 0,
                    "nome": _texto(linha[i_nome]),
                    "uf": _uf(linha[i_uf]),
                    "data": data_iso,
                    "valor": valor,
                }
                continue
            grupo["n"] += 1
            if classe == NULO:
                grupo["nulos"] += 1
            elif classe == INVALIDO:
                grupo["invalidos"] += 1
            if _melhor(grupo["data"], data_iso):
                grupo.update(
                    nome=_texto(linha[i_nome]), uf=_uf(linha[i_uf]), data=data_iso, valor=valor
                )
    return saida


def _mut_data_sem_largura_zero(path):
    """Não tira largura zero da data. Uma chamada a menos por linha no laço quente.

    Escrito por extenso, e não como `_data(s.strip())`: delegar para `_data`
    devolveria o `.translate()` que este mutante existe para tirar, e o mutante
    passaria a testar a si mesmo. O `--selftest` não pegaria — o mutante seria
    igual à referência e simplesmente falharia como ela passa. Quem pega é o
    `_assert_dataset_has_teeth` do `make_data.py`, que exige de cada mutante
    pelo menos uma divergência real contra o gate.
    """

    def data(bruto):
        s = bruto.strip()
        if not s or s.upper() in _SENTINELAS:
            return None
        tamanho = len(s)
        try:
            if tamanho == 10 and s[4] == "-" and s[7] == "-":
                ano, mes, dia = int(s[0:4]), int(s[5:7]), int(s[8:10])
            elif tamanho == 10 and s[2] == "/" and s[5] == "/":
                dia, mes, ano = int(s[0:2]), int(s[3:5]), int(s[6:10])
            elif tamanho == 8 and s[2] == "-" and s[5] == "-":
                dia, mes, aa = int(s[0:2]), int(s[3:5]), int(s[6:8])
                ano = _ano_de_dois_digitos(aa)
            else:
                return None
        except ValueError:
            return None
        if not _valido_no_calendario(ano, mes, dia):
            return None
        return f"{ano:04d}-{mes:02d}-{dia:02d}"

    return _pipeline(path, data_fn=data)


def _mut_bissexto_so_mod4(path):
    """`ano % 4 == 0` e pronto. Esquece que 2100 não é bissexto e 2000 é."""

    def data(bruto):
        s = bruto.translate(_LARGURA_ZERO).strip()
        if not s or s.upper() in _SENTINELAS:
            return None
        tamanho = len(s)
        try:
            if tamanho == 10 and s[4] == "-" and s[7] == "-":
                ano, mes, dia = int(s[0:4]), int(s[5:7]), int(s[8:10])
            elif tamanho == 10 and s[2] == "/" and s[5] == "/":
                dia, mes, ano = int(s[0:2]), int(s[3:5]), int(s[6:10])
            elif tamanho == 8 and s[2] == "-" and s[5] == "-":
                dia, mes, aa = int(s[0:2]), int(s[3:5]), int(s[6:8])
                ano = _ano_de_dois_digitos(aa)
            else:
                return None
        except ValueError:
            return None
        if mes < 1 or mes > 12 or dia < 1 or ano < 1 or ano > 9999:
            return None
        limite = 29 if (mes == 2 and ano % 4 == 0) else _DIAS_NO_MES[mes]
        if dia > limite:
            return None
        return f"{ano:04d}-{mes:02d}-{dia:02d}"

    return _pipeline(path, data_fn=data)


def _mut_sem_utf8_sig(path):
    """Abre como `utf-8` e o BOM fica colado no nome da primeira coluna."""
    saida: dict[str, dict] = {}
    with open(path, newline="", encoding="utf-8") as fh:
        leitor = csv.reader(fh)
        cabecalho = next(leitor, None)
        if cabecalho is None:
            return saida
        posicao = {nome: i for i, nome in enumerate(cabecalho)}
        i_doc, i_nome, i_uf, i_data, i_valor = (posicao[c] for c in COLUNAS)
        for linha in leitor:
            chave = _doc(linha[i_doc])
            if chave is None:
                continue
            valor, classe = _valor(linha[i_valor])
            data_iso = _data(linha[i_data])
            grupo = saida.get(chave)
            if grupo is None:
                saida[chave] = {
                    "n": 1,
                    "nulos": 1 if classe == NULO else 0,
                    "invalidos": 1 if classe == INVALIDO else 0,
                    "nome": _texto(linha[i_nome]),
                    "uf": _uf(linha[i_uf]),
                    "data": data_iso,
                    "valor": valor,
                }
                continue
            grupo["n"] += 1
            if classe == NULO:
                grupo["nulos"] += 1
            elif classe == INVALIDO:
                grupo["invalidos"] += 1
            if _melhor(grupo["data"], data_iso):
                grupo.update(
                    nome=_texto(linha[i_nome]), uf=_uf(linha[i_uf]), data=data_iso, valor=valor
                )
    return saida


MUTANTS = evalkit.MutantSuite(
    reference=reference,
    mutants=[
        ("sem_nfc", _mut_sem_nfc),
        ("texto_so_strip", _mut_texto_so_strip),
        ("texto_sem_largura_zero", _mut_texto_sem_largura_zero),
        ("data_mes_primeiro", _mut_data_mes_primeiro),
        ("pivot_ano_50", _mut_pivot_ano_50),
        ("decimal_sempre_br", _mut_decimal_sempre_br),
        ("parenteses_positivos", _mut_parenteses_positivos),
        ("traco_nao_e_sentinela", _mut_traco_nao_e_sentinela),
        ("uf_com_acento", _mut_uf_com_acento),
        ("uf_desconhecida_vira_texto", _mut_uf_desconhecida_vira_texto),
        ("dedup_primeiro_vence", _mut_dedup_primeiro_vence),
        ("dedup_ignora_data", _mut_dedup_ignora_data),
        ("doc_sem_padding", _mut_doc_sem_padding),
        ("colunas_por_posicao", _mut_colunas_por_posicao),
        ("split_por_virgula", _mut_split_por_virgula),
        ("data_sem_largura_zero", _mut_data_sem_largura_zero),
        ("bissexto_so_mod4", _mut_bissexto_so_mod4),
        ("sem_utf8_sig", _mut_sem_utf8_sig),
    ],
)


# ------------------------------------------------------------------- regimes

_ALIAS_DIR: tempfile.TemporaryDirectory | None = None


def _alias_dir() -> str:
    """Diretório de symlinks descartáveis, criado sob demanda e removido na saída."""
    global _ALIAS_DIR
    if _ALIAS_DIR is None:
        _ALIAS_DIR = tempfile.TemporaryDirectory(prefix="csv_normalize-alias-")
        atexit.register(_ALIAS_DIR.cleanup)
    return _ALIAS_DIR.name


def regimes() -> list[evalkit.Regime]:
    """Três FORMAS de dado, não três repetições da mesma.

    O caminho entregue muda a cada execução (symlink novo para o mesmo
    conteúdo). Isso não muda nada para quem processa o arquivo e derruba quem
    memoiza a saída indexada pelo caminho.
    """
    descricoes = {
        "limpo": "ASCII, datas ISO, decimais simples, quase sem duplicata",
        "sujo": "acento combinante, espaço estranho, decimal BR/US, sentinelas",
        "dup": "poucos documentos, muitas linhas por documento",
    }
    saida = []
    for arquivo in PERF_FILES:
        nome = arquivo[len("perf_") : -len(".csv")]
        alvo = str(data(arquivo))
        saida.append(
            evalkit.Regime(
                nome,
                (alvo,),
                descricoes[nome],
                args_factory=lambda alvo=alvo: (evalkit.unique_alias(alvo, _alias_dir()),),
            )
        )
    return saida


def _pisos() -> dict[str, float]:
    """Custo de só ler os bytes de cada regime. O limite inferior físico."""
    return {
        arquivo[len("perf_") : -len(".csv")]: evalkit.read_floor([data(arquivo)])
        for arquivo in PERF_FILES
    }


# ---------------------------------------------------------------------- main


def main() -> int:
    args = evalkit.standard_parser(__doc__.splitlines()[0]).parse_args()

    ok_dados, detalhe = datakit.verify_lock(HERE)
    if not ok_dados:
        if args.selftest or args.budget:
            print(f"dataset: {detalhe}", file=sys.stderr)
            return 1
        evalkit.emit_failure(f"dataset inválido: {detalhe}")
        return 0

    if args.selftest:
        passou = MUTANTS.selftest(GATE)
        # O seed também é julgado: um seed que não passa no próprio gate é um
        # target quebrado, e é um erro barato de cometer ao mexer no contrato.
        seed_fn = contracts.as_callable(
            evalkit.load_module(HERE / "seed" / ENTRYPOINT, "seedmod"), SYMBOL
        )
        ok_seed, detalhe_seed = GATE.check(seed_fn)
        print(
            f"\n  {'PASS' if ok_seed else 'FAIL'}  SEED (deve passar){' ' * 27}{detalhe_seed[:70]}"
        )
        return 0 if (passou and ok_seed) else 1

    if args.budget:
        # Mede o SEED, não a referência: é o seed que o agente paga no passo 1,
        # e dimensionar pelo candidato rápido foi precisamente a Falha 2.
        seed_fn = contracts.as_callable(
            evalkit.load_module(HERE / "seed" / ENTRYPOINT, "seedmod"), SYMBOL
        )
        corrida_seed = evalkit.measure(seed_fn, regimes(), repeats=3, warmup=1)
        corrida_ref = evalkit.measure(reference, regimes(), repeats=3, warmup=1)
        saudavel, mensagem = evalkit.budget_report(
            corrida_seed.wall_s, min(corrida_ref.per_regime.values())
        )
        print(mensagem)
        print(f"  seed:       {corrida_seed.notes()}")
        print(f"  referência: {corrida_ref.notes()}")
        pisos = _pisos()
        print("  piso de leitura: " + ", ".join(f"{k}={v * 1000:.1f}ms" for k, v in pisos.items()))
        return 0 if saudavel else 1

    if args.baselines:
        medicao = evalkit.measure(reference, regimes(), repeats=3, warmup=1)
        evalkit.emit_baselines({"referencia_passe_unico": medicao.throughput()})
        return 0

    candidato = evalkit.candidate_path(args.workdir, ENTRYPOINT)
    if not candidato.exists():
        evalkit.emit_failure(f"{ENTRYPOINT} ausente em {args.workdir}")
        return 0

    ok_imports, detalhe = contracts.stdlib_only(str(candidato))
    if not ok_imports:
        # `stdlib_only` já devolve uma frase completa e diz qual dos dois motivos
        # reprovou (não compila / importa de fora da stdlib). Embrulhá-la num
        # prefixo próprio mandaria o agente investigar a coisa errada.
        evalkit.emit_failure(detalhe)
        return 0

    try:
        modulo = evalkit.load_module(candidato)
        fn = contracts.as_callable(modulo, SYMBOL)
    except Exception as exc:  # noqa: BLE001
        evalkit.emit_failure(f"{type(exc).__name__}: {exc}")
        return 0

    ok_gate, detalhe = GATE.check(fn)
    if not ok_gate:
        evalkit.emit_failure(f"gate: {detalhe}")
        return 0

    # Caminho novo por execução (acima, em `regimes`) derruba cache indexado por
    # caminho. Não derruba cache indexado pelo CONTEÚDO: medido neste alvo,
    # 130,9x de score falso com a saída correta e o mesmo fingerprint. Módulo
    # novo por execução derruba qualquer cache em processo; a proibição de
    # escrever em disco derruba o que sobreviveria às duas.
    violacoes: list[str] = []

    def fresh():
        chamada = contracts.as_callable(evalkit.load_module(candidato, "cand_timed"), SYMBOL)

        def guardada(*args):
            with evalkit.no_disk_writes(violacoes):
                return chamada(*args)

        return guardada

    try:
        medicao = evalkit.measure(fn, regimes(), repeats=5, warmup=1, fn_factory=fresh)
    except Exception as exc:  # noqa: BLE001
        evalkit.emit_failure(f"falhou durante a medição: {type(exc).__name__}: {exc}")
        return 0

    if violacoes:
        evalkit.emit_failure(f"o candidato escreveu em disco durante a medição: {violacoes[0]}")
        return 0

    suspeito, detalhe_fisica = evalkit.implausible_speed(medicao.per_regime, _pisos())
    if suspeito:
        evalkit.emit_failure(f"velocidade implausível — {detalhe_fisica}")
        return 0

    digest = fingerprint(fn(str(data(GATE_FILE))))
    evalkit.emit_success(
        medicao.throughput(),
        notes=f"gate=ok fingerprint={digest} {medicao.notes()}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
