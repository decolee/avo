"""Gera os datasets congelados do target csv_normalize.

Quatro arquivos, dois papéis que não se misturam:

  perf_limpo / perf_sujo / perf_dup  -> só medem tempo. Três *formas* de dado,
      não três repetições da mesma. `limpo` é ASCII com data ISO e decimal
      simples — é onde um caminho rápido para o caso comum se paga. `sujo` tem
      acento combinante, espaço estranho e decimal nos dois formatos — é onde
      esse caminho rápido precisa saber cair fora. `dup` tem poucos documentos e
      muitas linhas por documento — é onde a estratégia de deduplicação aparece.
      Uma otimização que só serve a uma dessas formas melhora um regime e
      regride outro, e a média geométrica cobra a conta.

  gate_adv  -> decide `correct`, e só ele. Setenta e poucas linhas, cada uma
      escrita para punir uma suposição específica: BOM, CRLF misturado com LF,
      vírgula e quebra de linha dentro de campo citado, aspas duplicadas, acento
      combinante, espaço não-quebrável, largura zero, data ambígua, data fora do
      calendário, decimal nos dois formatos, negativo entre parênteses, todas as
      sentinelas de nulo e duplicatas que exercitam o desempate.

Por que os dois não podem ser o mesmo arquivo: em normalização, o atalho rápido
e o atalho errado são o MESMO atalho. `linha.split(",")` é várias vezes mais
rápido que o módulo `csv` e funciona perfeitamente enquanto nenhum campo tiver
vírgula citada — e um arquivo de performance, que precisa ser grande e por isso
é gerado por regra, nunca tem. Um gate que rodasse ali aprovaria o atalho, e a
busca inteira convergiria para código que quebra no primeiro arquivo real.

A ORDEM DAS COLUNAS É DIFERENTE entre perf e gate, de propósito. Treze colunas,
quatro usadas; quem decorar as posições em vez de ler o cabeçalho lê o município
achando que é o valor. Isso não é maldade gratuita: é a mesma classe de suposição
que o `split(",")` codifica, e ela precisa ter consequência em algum lugar.

Garantia de boa-formação: o gerador se recusa a escrever um `gate_adv` que não
distinga a normalização correta da ingênua. A asserção não é decorativa — é a
Falha 1 virada em código.
"""

from __future__ import annotations

import csv
import io
import random
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from labkit import datakit, evalkit  # noqa: E402

#: Layout dos arquivos de performance. `doc` na posição 1, `nome` na 2,
#: `data_ref` na 6, `valor` na 8 — decore por sua conta e risco.
COLUNAS_PERF = (
    "id",
    "doc",
    "nome",
    "fantasia",
    "municipio",
    "uf",
    "data_ref",
    "data_cad",
    "valor",
    "valor_bruto",
    "status",
    "canal",
    "obs",
)

#: Mesmas treze colunas, outra ordem. O cabeçalho é a fonte da verdade.
COLUNAS_GATE = (
    "obs",
    "nome",
    "valor",
    "doc",
    "id",
    "status",
    "uf",
    "data_cad",
    "municipio",
    "valor_bruto",
    "canal",
    "data_ref",
    "fantasia",
)

PRENOMES = (
    "Jose",
    "Maria",
    "Antonio",
    "Ana",
    "Paulo",
    "Carla",
    "Bruno",
    "Fernanda",
    "Ricardo",
    "Luciana",
    "Marcos",
    "Patricia",
    "Rafael",
    "Juliana",
    "Eduardo",
    "Camila",
)
SOBRENOMES = (
    "Silva",
    "Santos",
    "Oliveira",
    "Souza",
    "Pereira",
    "Lima",
    "Carvalho",
    "Ferreira",
    "Ribeiro",
    "Almeida",
    "Barbosa",
    "Rocha",
)
#: Versões acentuadas: matéria-prima do regime `sujo`, onde NFC custa de verdade.
PRENOMES_ACENTUADOS = (
    "José",
    "Antônio",
    "Luís",
    "Ângela",
    "Inês",
    "Cecília",
    "Vitória",
    "Fábio",
    "Mônica",
    "Estêvão",
    "Conceição",
    "Sebastião",
)
MUNICIPIOS = ("São Paulo", "Rio de Janeiro", "Belo Horizonte", "Curitiba", "Recife", "Salvador")
UFS = ("SP", "RJ", "MG", "PR", "PE", "BA")
STATUS = ("ATIVO", "ativo", "Inativo", "SUSPENSO", "")
CANAIS = ("web", "loja", "call-center", "parceiro")

#: Espaços que não são o espaço comum. Todos satisfazem `str.isspace()`, então
#: `" ".join(s.split())` os trata direito e `strip()` sozinho não.
ESPACOS = ("\u00a0", "\u2009", "\u202f", "\t", "\u3000")
#: Largura zero: NÃO satisfazem `isspace()`. `split()` não os vê.
LARGURA_ZERO = ("\u200b", "\u200c", "\ufeff")

SENTINELAS = ("", "NULL", "N/A", "-", "   ", "n/a", "\u00a0")


# ------------------------------------------------------------------ escrita


def _linha_csv(campos, terminador: str = "\n") -> str:
    """Uma linha CSV corretamente citada, com o terminador que eu escolher.

    Passar pelo `csv.writer` em vez de montar a string à mão é o que garante que
    a aspa duplicada e a vírgula citada estejam certas — se o gerador errar a
    citação, o gate estará medindo um bug meu em vez de um bug do candidato.
    """
    buf = io.StringIO()
    csv.writer(buf, lineterminator=terminador).writerow(campos)
    return buf.getvalue()


def _escrever_perf(path: Path, linhas: list[dict], com_bom: bool) -> None:
    codificacao = "utf-8-sig" if com_bom else "utf-8"
    with open(path, "w", newline="", encoding=codificacao) as fh:
        escritor = csv.writer(fh, lineterminator="\n")
        escritor.writerow(COLUNAS_PERF)
        for linha in linhas:
            escritor.writerow([linha[c] for c in COLUNAS_PERF])


# ------------------------------------------------------- dados de performance


def _sujar_texto(rnd: random.Random, nome: str) -> str:
    """Aplica as sujeiras de export legado, cada uma com sua probabilidade."""
    if rnd.random() < 0.35:
        nome = unicodedata.normalize("NFD", nome)
    if rnd.random() < 0.40:
        pos = nome.find(" ")
        if pos > 0:
            nome = nome[:pos] + rnd.choice(ESPACOS) + " " + nome[pos + 1 :]
    if rnd.random() < 0.20:
        pos = rnd.randrange(1, max(2, len(nome)))
        nome = nome[:pos] + rnd.choice(LARGURA_ZERO) + nome[pos:]
    if rnd.random() < 0.45:
        nome = rnd.choice(ESPACOS) + " " + nome + "  "
    if rnd.random() < 0.30:
        nome = nome.upper() if rnd.random() < 0.5 else nome.lower()
    return nome


def _doc_formatado(rnd: random.Random, numero: int, cnpj: bool = False) -> str:
    if cnpj:
        d = f"{numero:014d}"
        cru = f"{d[0:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:14]}"
    else:
        d = f"{numero:011d}"
        cru = f"{d[0:3]}.{d[3:6]}.{d[6:9]}-{d[9:11]}"
    if rnd.random() < 0.30:
        return d.lstrip("0") or "0"  # sem pontuação e sem zeros à esquerda
    return cru


def _data_limpa(rnd: random.Random) -> str:
    return f"{rnd.randrange(2018, 2025):04d}-{rnd.randrange(1, 13):02d}-{rnd.randrange(1, 29):02d}"


def _data_suja(rnd: random.Random) -> str:
    escolha = rnd.random()
    dia, mes, ano = rnd.randrange(1, 29), rnd.randrange(1, 13), rnd.randrange(2018, 2025)
    if escolha < 0.30:
        return f"{dia:02d}/{mes:02d}/{ano:04d}"
    if escolha < 0.55:
        return f"{ano:04d}-{mes:02d}-{dia:02d}"
    if escolha < 0.75:
        return f"{dia:02d}-{mes:02d}-{ano % 100:02d}"
    if escolha < 0.85:
        return rnd.choice(SENTINELAS)
    if escolha < 0.92:
        return f"{dia:02d}/{mes:02d}/{ano % 100:02d}"  # forma não suportada -> None
    return f"31/{rnd.choice((2, 4, 6, 9, 11)):02d}/{ano:04d}"  # fora do calendário -> None


def _valor_limpo(rnd: random.Random) -> str:
    if rnd.random() < 0.12:
        return str(rnd.randrange(1, 9999))
    return f"{rnd.uniform(-5000, 20000):.2f}"


def _valor_sujo(rnd: random.Random) -> str:
    escolha = rnd.random()
    x = rnd.uniform(0, 250000)
    inteiro, centavos = int(x), int(round((x - int(x)) * 100))
    br = f"{inteiro:,}".replace(",", ".") + f",{centavos:02d}"
    us = f"{inteiro:,}" + f".{centavos:02d}"
    if escolha < 0.28:
        return br
    if escolha < 0.44:
        return us
    if escolha < 0.54:
        return f"({br})"
    if escolha < 0.62:
        return f"R$ {br}"
    if escolha < 0.70:
        return f"-{br}"
    if escolha < 0.80:
        return f"{x:.2f}"
    if escolha < 0.90:
        return rnd.choice(SENTINELAS)
    if escolha < 0.95:
        return f"{inteiro}"
    return "sem informacao"  # inválido, não sentinela


def _linhas_perf(
    n: int, n_docs: int, seed: int, sujo: bool, cnpj_frac: float = 0.25
) -> list[dict]:
    rnd = random.Random(seed)
    # CNPJ nasce com 13-14 dígitos e CPF com 8-11: o mesmo documento tem que
    # cair na mesma chave venha ele pontuado ou cru. Um CNPJ com zeros à
    # esquerda escrito sem pontuação viraria CPF depois do `lstrip`, e a mesma
    # entidade apareceria como duas chaves — ruído puro num arquivo cujo único
    # trabalho é medir tempo.
    cnpjs = {i for i in range(n_docs) if rnd.random() < cnpj_frac}
    docs = [
        rnd.randrange(10**13, 10**14) if i in cnpjs else rnd.randrange(10**7, 10**11)
        for i in range(n_docs)
    ]
    linhas = []
    for i in range(n):
        idx = rnd.randrange(n_docs)
        if sujo:
            nome = _sujar_texto(
                rnd, f"{rnd.choice(PRENOMES_ACENTUADOS)} {rnd.choice(SOBRENOMES)}"
            )
            data_ref, valor = _data_suja(rnd), _valor_sujo(rnd)
        else:
            nome = f"{rnd.choice(PRENOMES)} {rnd.choice(SOBRENOMES)}"
            data_ref, valor = _data_limpa(rnd), _valor_limpo(rnd)
        # Uma fatia pequena de campos citados também no benchmark: o caminho
        # rápido que ignora aspas tem que ser exercitado aqui, não só no gate.
        obs = f"lote {i % 977:03d}"
        if rnd.random() < 0.08:
            obs = f'ref {i}, item {i % 13}, "conferido"'
        linhas.append(
            {
                "id": i,
                "doc": _doc_formatado(rnd, docs[idx], cnpj=idx in cnpjs),
                "nome": nome,
                "fantasia": f"UNIDADE {i % 400:03d}",
                "municipio": rnd.choice(MUNICIPIOS),
                "uf": rnd.choice(UFS),
                "data_ref": data_ref,
                "data_cad": _data_limpa(rnd),
                "valor": valor,
                "valor_bruto": f"{rnd.uniform(0, 30000):.2f}",
                "status": rnd.choice(STATUS),
                "canal": rnd.choice(CANAIS),
                "obs": obs,
            }
        )
    return linhas


# ------------------------------------------------------------- dado do gate


def _gate_linhas() -> list[dict]:
    """Cada linha existe para punir uma suposição. Os comentários dizem qual."""
    linhas: list[dict] = []

    def add(doc: str, nome: str, data_ref: str, valor: str, obs: str = "ok") -> None:
        i = len(linhas)
        linhas.append(
            {
                "id": 1000 + i,
                "doc": doc,
                "nome": nome,
                "fantasia": f"FANTASIA {i:03d}",
                "municipio": MUNICIPIOS[i % len(MUNICIPIOS)],
                "uf": UFS[i % len(UFS)],
                "data_ref": data_ref,
                "data_cad": "2024-01-01",
                "valor": valor,
                "valor_bruto": "0,00",
                "status": STATUS[i % len(STATUS)],
                "canal": CANAIS[i % len(CANAIS)],
                "obs": obs,
            }
        )

    # --- texto: unicode, espaço e citação ---------------------------------
    add("111.111.111-11", "José  da   Silva", "2024-01-02", "10,00")  # espaço interno duplo
    add("111.111.111-12", "Jose\u0301 da Silva", "2024-01-02", "10,00")  # NFD: mesmo texto
    add("111.111.111-13", " \u00a0Maria\u00a0\u00a0 Conceição \u00a0", "2024-01-02", "10,00")
    add("111.111.111-14", "An\u200bton\u200bio Ângelo", "2024-01-02", "10,00")  # largura zero
    add("111.111.111-15", "Paulo\r\nRoberto", "2024-01-02", "10,00")  # quebra dentro do campo
    add("111.111.111-16", "Silva, João Pedro", "2024-01-02", "10,00")  # vírgula citada
    add("111.111.111-17", 'Ana "Nina" Souza', "2024-01-02", "10,00")  # aspas duplicadas
    add("111.111.111-18", "\u3000Luís\tGonzaga\u2009", "2024-01-02", "10,00")  # espaços exóticos
    add("111.111.111-19", "Conceic\u0327a\u0303o Ferreira", "2024-01-02", "10,00")  # NFD duplo
    add("111.111.111-20", "  ", "2024-01-02", "10,00")  # nome só de espaço -> ""
    add(
        "111.111.111-21",
        "Marcos Vinícius",
        "2024-01-02",
        "10,00",
        'obs com, vírgula e "aspas"\ne quebra',
    )

    # --- datas ------------------------------------------------------------
    add("222.222.222-01", "Data Ambigua A", "03/04/2024", "1,00")  # dia primeiro: 03 de abril
    add("222.222.222-02", "Data Ambigua B", "12/11/2023", "1,00")  # dia primeiro: 12 de novembro
    add("222.222.222-03", "Data Iso", "2024-04-03", "1,00")
    add("222.222.222-04", "Ano Dois Digitos A", "05-06-60", "1,00")  # janela POSIX: 2060
    add("222.222.222-05", "Ano Dois Digitos B", "05-06-68", "1,00")  # 2068 (limite superior)
    add("222.222.222-06", "Ano Dois Digitos C", "05-06-69", "1,00")  # 1969 (outro lado)
    add("222.222.222-07", "Data Impossivel", "31/02/2024", "1,00")  # fora do calendário -> None
    add("222.222.222-08", "Bissexto Valido", "29/02/2024", "1,00")
    add("222.222.222-09", "Bissexto Invalido", "29/02/2023", "1,00")  # -> None
    add("222.222.222-10", "Mes Absurdo", "13/13/2024", "1,00")  # -> None nos dois sentidos
    add("222.222.222-11", "Forma Nao Suportada", "05/06/24", "1,00")  # DD/MM/AA -> None
    add("222.222.222-12", "Data Sentinela A", "N/A", "1,00")
    add("222.222.222-13", "Data Sentinela B", "-", "1,00")
    add("222.222.222-14", "Data Vazia", "", "1,00")
    add("222.222.222-15", "Iso Mes Absurdo", "2024-13-01", "1,00")  # -> None
    add("222.222.222-16", "Mes Primeiro Seria Valido", "04/13/2024", "1,00")  # dia 4, mês 13 -> None
    add("222.222.222-17", "Data Com Espaco", " 2024-04-03 ", "1,00")

    # --- decimais ---------------------------------------------------------
    add("333.333.333-01", "Decimal Br", "1.234,56", "1.234,56")
    add("333.333.333-02", "Decimal Us", "2024-01-02", "1,234.56")
    add("333.333.333-03", "Parenteses Br", "2024-01-02", "(1.234,56)")
    add("333.333.333-04", "Parenteses Us", "2024-01-02", "(1,234.56)")
    add("333.333.333-05", "Moeda", "2024-01-02", "R$ 1.234,56")
    add("333.333.333-06", "Sinal E Moeda", "2024-01-02", "-R$ 45,90")
    add("333.333.333-07", "Virgula Decimal Curta", "2024-01-02", "1,5")
    add("333.333.333-08", "Ponto Milhar", "2024-01-02", "1.500")  # 3 dígitos -> milhar
    add("333.333.333-09", "Ponto Decimal", "2024-01-02", "1.23")  # 2 dígitos -> decimal
    add("333.333.333-10", "Virgula Milhar", "2024-01-02", "1,500")  # 3 dígitos -> milhar
    add("333.333.333-11", "Milhar Duplo", "2024-01-02", "1.234.567,89")
    add("333.333.333-12", "Tudo Junto", "2024-01-02", "(R$ 1.234.567,89)")
    add("333.333.333-13", "Zero Virgula Tres", "2024-01-02", "0,005")  # regra literal -> 5.0
    add("333.333.333-14", "Arredonda", "2024-01-02", "12,3456")  # -> 12.35
    add("333.333.333-15", "Texto Puro", "2024-01-02", "sem informacao")  # inválido
    add("333.333.333-16", "So Moeda", "2024-01-02", "R$")  # inválido
    add("333.333.333-17", "Sentinela Null", "2024-01-02", "NULL")
    add("333.333.333-18", "Sentinela Traco", "2024-01-02", "-")  # nulo, NÃO inválido
    add("333.333.333-19", "Sentinela Espacos", "2024-01-02", "   ")
    add("333.333.333-20", "Sentinela Nbsp", "2024-01-02", "\u00a0")
    add("333.333.333-21", "Sentinela Na", "2024-01-02", "n/a")  # caixa não importa
    add("333.333.333-22", "Sentinela Vazia", "2024-01-02", "")
    add("333.333.333-23", "Negativo Pequeno", "2024-01-02", "-0,50")
    add("333.333.333-24", "Dolar", "2024-01-02", "$1,234.56")
    add("333.333.333-25", "Tres Casas", "2024-01-02", "12.345,678")  # -> 12345.68
    add("333.333.333-26", "Parenteses Com Espaco", "2024-01-02", "(  1.234,56  )")
    add("333.333.333-27", "Traco Duplo", "2024-01-02", "--")  # nulo
    add("333.333.333-28", "Largura Zero No Numero", "2024-01-02", "1.2\u200b34,56")

    # --- documento --------------------------------------------------------
    add("12.345.678/0001-99", "Cnpj Pontuado", "2024-01-02", "1,00")
    add("SEM DOCUMENTO", "Descartada A", "2024-01-02", "1,00")  # sem dígito -> descartada
    add("", "Descartada B", "2024-01-02", "1,00")  # vazio -> descartada
    add("123456789012345", "Descartada C", "2024-01-02", "1,00")  # 15 dígitos -> descartada
    add("123.456.789-09", "Cpf Pontuado", "2024-01-02", "1,00")  # mesma chave da próxima
    add("12345678909", "Cpf Cru Vence", "2024-06-02", "2,00")  # data maior -> vence

    # --- deduplicação e desempate ----------------------------------------
    add("444.444.444-01", "Antigo A", "2024-01-05", "10,00")
    add("444.444.444-01", "Vencedor B", "2024-03-10", "20,00")  # data mais recente vence
    add("444.444.444-01", "Meio C", "2024-02-01", "30,00")
    add("444.444.444-02", "Primeiro D", "2024-05-05", "1,00")
    add("444.444.444-02", "Segundo E", "2024-05-05", "2,00")  # empate: o último vence
    add("444.444.444-03", "Com Data G", "2020-01-01", "8,00")  # data ganha de sem data
    add("444.444.444-03", "Sem Data F", "NULL", "7,00")
    add("444.444.444-04", "Sem Data H", "", "3,00")
    add("444.444.444-04", "Sem Data I", "N/A", "4,00")  # ambas sem data: o último vence
    add("1234567", "Curto Perde", "2023-01-01", "5,00")  # vira 00001234567
    add("00001234567", "Zeros A Esquerda Vence", "2023-09-09", "6,00")  # mesma chave

    return linhas


def _texto_gate(linhas: list[dict]) -> str:
    """Monta o arquivo com BOM e terminadores alternados entre LF e CRLF."""
    partes = ["\ufeff" + _linha_csv(COLUNAS_GATE, "\r\n")]
    for i, linha in enumerate(linhas):
        terminador = "\r\n" if i % 3 == 0 else "\n"
        partes.append(_linha_csv([linha[c] for c in COLUNAS_GATE], terminador))
    return "".join(partes)


# ---------------------------------------------------------------- asserções


def _normalizacao_ingenua(path: str) -> dict:
    """O que sai de escrever "normaliza esse CSV" sem pensar duas vezes.

    `strip().lower()` sem NFC, `float()` direto no valor, `strptime` só no
    formato brasileiro, `setdefault` para deduplicar. Não é um espantalho: é
    literalmente o primeiro rascunho de qualquer um, e é contra ele que o
    gate_adv precisa ter mordida. Se este dicionário for igual ao da referência,
    o dataset não serve.
    """
    from datetime import datetime

    saida: dict[str, dict] = {}
    with open(path, newline="", encoding="utf-8-sig") as fh:
        leitor = csv.DictReader(fh)
        for linha in leitor:
            chave = "".join(c for c in (linha["doc"] or "") if c.isdigit())
            if not chave:
                continue
            try:
                valor = float((linha["valor"] or "").replace(",", ""))
            except ValueError:
                valor = None
            try:
                data_iso = datetime.strptime(linha["data_ref"].strip(), "%d/%m/%Y").strftime(
                    "%Y-%m-%d"
                )
            except ValueError:
                data_iso = None
            grupo = saida.setdefault(
                chave,
                {
                    "n": 0,
                    "nulos": 0,
                    "invalidos": 0,
                    "nome": (linha["nome"] or "").strip().upper(),
                    "data": data_iso,
                    "valor": valor,
                },
            )
            grupo["n"] += 1
            if valor is None:
                grupo["nulos"] += 1
    return saida


def _divergencias(esperado: dict, obtido: dict) -> int:
    """Quantas chaves diferem, contando ausência e sobra como divergência."""
    total = len(set(esperado) ^ set(obtido))
    for chave in set(esperado) & set(obtido):
        a, b = esperado[chave], obtido[chave]
        if any(a.get(c) != b.get(c) for c in ("n", "nulos", "invalidos", "nome", "data")):
            total += 1
        elif a.get("valor") != b.get("valor"):
            total += 1
    return total


#: Mínimo de registros em que a normalização ingênua tem que errar. Vinte é
#: arbitrário no valor e não no espírito: um punhado de divergências pode ser
#: acidente do gerador, vinte só acontece se o arquivo estiver de fato cobrindo
#: as armadilhas de propósito.
MINIMO_DIVERGENCIAS_INGENUAS = 20


def _assert_dataset_has_teeth(path: Path) -> None:
    """Prova que este arquivo separa a normalização correta da ingênua.

    Duas provas, porque elas cobrem coisas diferentes. A primeira é o espírito
    da Falha 1: contra o rascunho de qualquer engenheiro, o arquivo tem que
    divergir em muitos registros, não em um. A segunda é a rede fina: cada
    mutante declarado no avaliador tem que errar em pelo menos um registro,
    senão ele é decorativo e o selftest estaria dando falsa segurança.
    """
    avaliador = evalkit.load_module(HERE / "eval.py", "csvnorm_eval")
    esperado = avaliador.reference(str(path))

    if len(esperado) < 40:
        raise AssertionError(
            f"gate_adv produziu só {len(esperado)} chaves — pouco para cobrir as armadilhas."
        )

    divergentes = _divergencias(esperado, _normalizacao_ingenua(str(path)))
    if divergentes < MINIMO_DIVERGENCIAS_INGENUAS:
        raise AssertionError(
            f"a normalização ingênua diverge da referência em só {divergentes} registros "
            f"(mínimo {MINIMO_DIVERGENCIAS_INGENUAS}). O gate_adv não tem mordida: adicione "
            "casos de unicode, decimal e data ambígua."
        )

    cegos = []
    for nome, mutante in avaliador.MUTANTS.mutants:
        try:
            obtido = mutante(str(path))
        except Exception:  # noqa: BLE001 — mutante que explode já é divergência suficiente
            continue
        if _divergencias(esperado, obtido) == 0:
            cegos.append(nome)
    if cegos:
        raise AssertionError(
            "gate_adv não distingue estes mutantes da referência: "
            + ", ".join(cegos)
            + ". Eles passariam no selftest sem o gate ter olhado para nada."
        )


def _build_gate(path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        fh.write(_texto_gate(_gate_linhas()))
    _assert_dataset_has_teeth(path)


# ------------------------------------------------------------------- specs

LINHAS_PERF = 13_000


def specs() -> list[datakit.DatasetSpec]:
    return [
        datakit.DatasetSpec(
            "perf_limpo.csv",
            lambda p: _escrever_perf(
                p, _linhas_perf(LINHAS_PERF, 9000, seed=21, sujo=False), com_bom=False
            ),
            purpose="ASCII, data ISO, decimal simples, quase sem duplicata",
            rows=LINHAS_PERF,
        ),
        datakit.DatasetSpec(
            "perf_sujo.csv",
            lambda p: _escrever_perf(
                p, _linhas_perf(LINHAS_PERF, 7000, seed=22, sujo=True), com_bom=True
            ),
            purpose="acento combinante, espaco estranho, decimal BR/US, sentinelas, BOM",
            rows=LINHAS_PERF,
        ),
        datakit.DatasetSpec(
            "perf_dup.csv",
            lambda p: _escrever_perf(
                p, _linhas_perf(LINHAS_PERF, 260, seed=23, sujo=True), com_bom=False
            ),
            purpose="poucos documentos, muitas linhas por documento",
            rows=LINHAS_PERF,
        ),
        datakit.DatasetSpec(
            "gate_adv.csv",
            _build_gate,
            purpose="UNICO dataset que decide correcao: BOM, CRLF, citacao, NFD, ambiguidade",
            rows=len(_gate_linhas()),
        ),
    ]


def main() -> int:
    report = datakit.generate(HERE, specs(), force="--force" in sys.argv)
    print(f"csv_normalize: {report.render()}")
    ok, detail = datakit.verify_lock(HERE)
    print(f"lock: {detail}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
