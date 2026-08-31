"""Gera os bancos de cadastro do target dedupe_match.

Sete arquivos, tres papeis que nao se misturam:

  records_<banco>.json  -> o que `match` recebe. SO campos de dado. Nenhum
      campo, prefixo de id ou ordenacao carrega a resposta: os registros sao
      embaralhados antes de receber id, entao id vizinho nao significa nada.

  labels_<banco>.json   -> o gabarito. Fica em arquivo SEPARADO porque a
      separacao e o que torna a regra "o candidato nao le o gabarito"
      verificavel em vez de aspiracional. O avaliador le; o candidato nunca ve.

  gate_bank.json        -> registros pequenos e deformados que decidem `correct`
      (forma da saida, determinismo, orcamento, pureza). Nao tem gabarito de
      proposito: neste target `correct` nao mede acerto, mede contrato.

Os tres bancos sao FORMAS de dado diferentes, nao repeticoes:

  pessoas   pessoas fisicas, corrupcao moderada. O caso base.
  empresas  razao social: sufixo societario que muda de forma (LTDA/LIMITADA),
            "&" virando "E", nome fantasia no lugar da razao social. O ruido e
            estrutural, nao tipografico — normalizacao de pessoa fisica nao
            transfere.
  ruidoso   pessoas fisicas com o dobro de erro de digitacao, mais campos
            ausentes e mais inversao de ordem de nome. E onde a similaridade
            aproximada decide.

Uma otimizacao que so vale em `pessoas` aparece la e some em `empresas` — e e
isso que torna a media geometrica dos tres um numero diagnostico em vez de so
um numero subindo.

NEGATIVOS DIFICEIS SAO A METADE CARA DO DATASET. Um banco so com positivos
premia quem devolve tudo. Aqui um terco dos registros vive dentro de um par
adversarial construido: homonimo exato na mesma cidade, nome a uma letra de
distancia, e domicilio compartilhado (mesmo telefone e mesmo endereco, pessoas
diferentes). Cada um desses pares tem, por construcao, ao menos um campo
presente dos dois lados que os separa — senao o teto de F1 seria inalcancavel e
o alvo estaria cobrando uma coisa impossivel.

Garantia de boa-formacao: o gerador se recusa a escrever um banco em que a
estrategia ingenua ja seja boa, ou em que os pares positivos sejam
inalcancaveis. As duas asercoes sao as Falhas 1 e 3 viradas em codigo.
"""

from __future__ import annotations

import json
import random
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from labkit import datakit  # noqa: E402

# --------------------------------------------------------------- catalogos

PRENOMES = (
    "José",
    "João",
    "Antônio",
    "Francisco",
    "Carlos",
    "Paulo",
    "Pedro",
    "Lucas",
    "Luiz",
    "Marcos",
    "Márcio",
    "Rafael",
    "Daniel",
    "Bruno",
    "Eduardo",
    "Felipe",
    "Rodrigo",
    "Gustavo",
    "Thiago",
    "André",
    "Fernando",
    "Ricardo",
    "Sérgio",
    "Maria",
    "Ana",
    "Francisca",
    "Antônia",
    "Adriana",
    "Juliana",
    "Márcia",
    "Fernanda",
    "Patrícia",
    "Aline",
    "Sandra",
    "Camila",
    "Amanda",
    "Bruna",
    "Jéssica",
    "Letícia",
    "Júlia",
    "Luciana",
    "Vanessa",
    "Mariana",
    "Beatriz",
    "Simone",
    "Cláudia",
    "Débora",
    "Renata",
    "Tatiane",
    "Vera",
)

MEIOS = (
    "de Souza",
    "dos Santos",
    "da Silva",
    "Augusto",
    "Henrique",
    "Cristina",
    "Aparecida",
    "do Carmo",
    "Eduardo",
    "Fernanda",
    "Regina",
    "Luiz",
    "Otávio",
    "",
    "",
    "",
)

SOBRENOMES = (
    "Silva",
    "Santos",
    "Oliveira",
    "Souza",
    "Rodrigues",
    "Ferreira",
    "Alves",
    "Pereira",
    "Lima",
    "Gomes",
    "Costa",
    "Ribeiro",
    "Martins",
    "Carvalho",
    "Almeida",
    "Lopes",
    "Soares",
    "Fernandes",
    "Vieira",
    "Barbosa",
    "Rocha",
    "Dias",
    "Nascimento",
    "Andrade",
    "Moreira",
    "Nunes",
    "Marques",
    "Machado",
    "Mendes",
    "Freitas",
    "Cardoso",
    "Ramos",
    "Gonçalves",
    "Araújo",
    "Correia",
    "Teixeira",
    "Azevedo",
    "Cavalcanti",
    "Monteiro",
    "Moraes",
    "Peixoto",
)

CIDADES = (
    ("São Paulo", "SP"),
    ("Rio de Janeiro", "RJ"),
    ("Belo Horizonte", "MG"),
    ("Porto Alegre", "RS"),
    ("Curitiba", "PR"),
    ("Salvador", "BA"),
    ("Fortaleza", "CE"),
    ("Recife", "PE"),
    ("Brasília", "DF"),
    ("Goiânia", "GO"),
    ("Campinas", "SP"),
    ("São Bernardo do Campo", "SP"),
    ("Ribeirão Preto", "SP"),
    ("Niterói", "RJ"),
    ("Florianópolis", "SC"),
    ("Vitória", "ES"),
    ("Maceió", "AL"),
    ("João Pessoa", "PB"),
    ("Uberlândia", "MG"),
    ("Juiz de Fora", "MG"),
)

DOMINIOS = (
    "gmail.com",
    "hotmail.com",
    "outlook.com",
    "uol.com.br",
    "terra.com.br",
    "yahoo.com.br",
    "bol.com.br",
    "ig.com.br",
)

TIPOS_LOGRADOURO = (
    ("Rua", "R."),
    ("Avenida", "Av."),
    ("Alameda", "Al."),
    ("Travessa", "Tv."),
    ("Praça", "Pç."),
    ("Estrada", "Estr."),
)

LOGRADOUROS = (
    "das Acácias",
    "Sete de Setembro",
    "Barão do Rio Branco",
    "São João",
    "Dom Pedro II",
    "Getúlio Vargas",
    "Santos Dumont",
    "das Palmeiras",
    "Marechal Deodoro",
    "Quinze de Novembro",
    "Tiradentes",
    "das Flores",
    "João Pessoa",
    "Voluntários da Pátria",
    "Duque de Caxias",
    "Amazonas",
)

RAMOS = (
    "Comercial",
    "Distribuidora",
    "Industrial",
    "Transportes",
    "Alimentos",
    "Construções",
    "Serviços",
    "Tecnologia",
    "Engenharia",
    "Confecções",
    "Farmacêutica",
    "Agropecuária",
    "Metalúrgica",
    "Logística",
    "Importadora",
    "Exportadora",
    "Papelaria",
    "Refrigeração",
    "Automação",
    "Consultoria",
    "Empreendimentos",
    "Participações",
    "Mineração",
    "Têxtil",
)

MARCAS = (
    "Acácia",
    "Andorinha",
    "Bandeirante",
    "Cristal",
    "Diamante",
    "Estrela",
    "Fênix",
    "Guarani",
    "Horizonte",
    "Ipiranga",
    "Jandaia",
    "Kairós",
    "Lumiar",
    "Marajoara",
    "Nordeste",
    "Oceano",
    "Paranapanema",
    "Quaresmeira",
    "Rio Verde",
    "Sertão",
    "Tupinambá",
    "União",
    "Vanguarda",
    "Xingu",
    "Aurora",
    "Bonsucesso",
    "Caiçara",
    "Dourado",
    "Embiara",
    "Farroupilha",
    "Girassol",
    "Hortência",
    "Itaúna",
    "Jequitibá",
    "Laranjeiras",
    "Mangueiral",
    "Natividade",
    "Orquídea",
    "Pindorama",
    "Quilombo",
    "Recanto",
    "Solimões",
    "Tamoio",
    "Ubatã",
    "Vitória Régia",
    "Zamboni",
)

SUFIXOS_PJ = ("LTDA", "S/A", "ME", "EIRELI", "EPP")


# ------------------------------------------------------- ruido tipografico


def sem_acento(texto: str) -> str:
    decomposto = unicodedata.normalize("NFD", texto)
    return "".join(c for c in decomposto if unicodedata.category(c) != "Mn")


def _typo(rnd: random.Random, texto: str) -> str:
    """Um erro de digitacao plausivel: transposicao, dedo gordo, ou letra a mais.

    Nao mexe na primeira letra por escolha: erro na inicial e raro em digitacao
    real e destruiria qualquer bloqueio por prefixo, que e uma tecnica legitima
    que o alvo quer premiar e nao inviabilizar.
    """
    if len(texto) < 5:
        return texto
    i = rnd.randrange(1, len(texto) - 1)
    if texto[i] == " " or texto[i - 1] == " ":
        i = min(i + 1, len(texto) - 2)
    modo = rnd.random()
    if modo < 0.40:  # transposicao
        return texto[:i] + texto[i + 1] + texto[i] + texto[i + 2 :]
    if modo < 0.70:  # letra dobrada
        return texto[:i] + texto[i] + texto[i:]
    if modo < 0.90:  # letra trocada por vizinha de teclado
        vizinhos = {
            "a": "s",
            "e": "r",
            "i": "o",
            "o": "p",
            "u": "y",
            "s": "a",
            "r": "t",
            "n": "m",
            "m": "n",
            "c": "v",
            "l": "k",
            "t": "y",
        }
        c = texto[i].lower()
        return texto[:i] + vizinhos.get(c, c) + texto[i + 1 :]
    return texto[:i] + texto[i + 1 :]  # letra faltando


def _formatar_telefone(rnd: random.Random, ddd: str, digitos: str) -> str:
    a, b = digitos[:5], digitos[5:]
    forma = rnd.randrange(6)
    if forma == 0:
        return f"({ddd}) {a}-{b}"
    if forma == 1:
        return f"{ddd}{a}{b}"
    if forma == 2:
        return f"+55 {ddd} {a}-{b}"
    if forma == 3:
        return f"0{ddd} {a} {b}"
    if forma == 4:
        return f"{ddd} {a}{b}"
    return f"({ddd}){a}-{b}"


def _formatar_data(rnd: random.Random, ano: int, mes: int, dia: int) -> str:
    """Tres formatos brasileiros para a MESMA data.

    Comparar `nascimento` como string crua faz duas variacoes da mesma pessoa
    parecerem pessoas diferentes — e faz um candidato que usa "data diferente
    logo nao e o mesmo" descartar positivos. Normalizar a data e um movimento
    legitimo, e o custo de nao fazer isso e visivel na precisao.
    """
    forma = rnd.randrange(3)
    if forma == 0:
        return f"{ano:04d}-{mes:02d}-{dia:02d}"
    if forma == 1:
        return f"{dia:02d}/{mes:02d}/{ano:04d}"
    return f"{dia:02d}.{mes:02d}.{ano:04d}"


def _formatar_documento(rnd: random.Random, digitos: str, pj: bool) -> str:
    if pj:
        if rnd.random() < 0.5:
            return f"{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/{digitos[8:12]}-{digitos[12:]}"
        return digitos
    if rnd.random() < 0.5:
        return f"{digitos[:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:]}"
    return digitos


# ----------------------------------------------------------------- perfis


@dataclass
class Perfil:
    """Quanto de cada tipo de erro um banco carrega, e de que tamanho ele e."""

    nome: str
    seed: int
    pj: bool = False
    #: probabilidade de uma variante sair com o nome intacto. E o teto de recall
    #: da estrategia ingenua (igualdade de nome normalizado) e, portanto, o
    #: principal botao de headroom do alvo.
    nome_intacto: float = 0.26
    typos: float = 0.40
    typos_extra: float = 0.10
    inverte_ordem: float = 0.22
    abrevia_meio: float = 0.30
    tira_acento: float = 0.55
    campo_ausente: float = 0.18
    singletons: int = 900
    clusters_2: int = 200
    clusters_3: int = 85
    clusters_4: int = 35
    homonimos: int = 120
    quase_homonimos: int = 100
    domicilios: int = 60


PERFIS = (
    Perfil("pessoas", seed=4101, nome_intacto=0.13, homonimos=165),
    Perfil(
        "empresas",
        seed=4102,
        pj=True,
        nome_intacto=0.24,
        typos=0.30,
        inverte_ordem=0.05,
        abrevia_meio=0.10,
        tira_acento=0.50,
        campo_ausente=0.16,
    ),
    Perfil(
        "ruidoso",
        seed=4103,
        nome_intacto=0.15,
        typos=0.70,
        typos_extra=0.35,
        inverte_ordem=0.35,
        abrevia_meio=0.45,
        tira_acento=0.75,
        campo_ausente=0.32,
    ),
)


# ------------------------------------------------------------- entidades


def _entidade_pf(rnd: random.Random) -> dict:
    prenome = rnd.choice(PRENOMES)
    meio = rnd.choice(MEIOS)
    sobrenome = rnd.choice(SOBRENOMES)
    segundo = rnd.choice(SOBRENOMES) if rnd.random() < 0.45 else ""
    partes = [p for p in (prenome, meio, sobrenome, segundo) if p]
    cidade, uf = rnd.choice(CIDADES)
    tipo, _ = rnd.choice(TIPOS_LOGRADOURO)
    return {
        "nome": " ".join(partes),
        "cidade": cidade,
        "uf": uf,
        "ddd": f"{rnd.randrange(11, 99):02d}",
        "fone": f"9{rnd.randrange(10**8):08d}",
        "local_email": f"{sem_acento(prenome).lower()}.{sem_acento(sobrenome).lower()}",
        "num_email": str(rnd.randrange(1000)),
        "dominio": rnd.choice(DOMINIOS),
        "doc": f"{rnd.randrange(10**11):011d}",
        "tem_doc": rnd.random() < 0.28,
        "ano": rnd.randrange(1945, 2005),
        "mes": rnd.randrange(1, 13),
        "dia": rnd.randrange(1, 29),
        "tem_data": rnd.random() < 0.72,
        "tipo_log": tipo,
        "logradouro": rnd.choice(LOGRADOUROS),
        "numero": rnd.randrange(10, 4000),
        "complemento": f"apto {rnd.randrange(1, 200)}" if rnd.random() < 0.4 else "",
    }


def _entidade_pj(rnd: random.Random) -> dict:
    marca = rnd.choice(MARCAS)
    ramo = rnd.choice(RAMOS)
    sufixo = rnd.choice(SUFIXOS_PJ)
    segunda = rnd.choice(MARCAS)
    if rnd.random() < 0.30:
        razao = f"{ramo} {marca} {segunda} {sufixo}"
    elif rnd.random() < 0.5:
        razao = f"{marca} {segunda} {ramo} {sufixo}"
    else:
        razao = f"{marca} & {segunda} {ramo} {sufixo}"
    cidade, uf = rnd.choice(CIDADES)
    tipo, _ = rnd.choice(TIPOS_LOGRADOURO)
    slug = sem_acento(marca).lower().replace(" ", "")
    return {
        "nome": razao,
        "fantasia": f"{marca} {ramo}",
        "sufixo": sufixo,
        "cidade": cidade,
        "uf": uf,
        "ddd": f"{rnd.randrange(11, 99):02d}",
        "fone": f"3{rnd.randrange(10**8):08d}",
        "local_email": f"contato.{slug}",
        "num_email": str(rnd.randrange(100)),
        "dominio": f"{slug}.com.br",
        "doc": f"{rnd.randrange(10**14):014d}",
        "tem_doc": rnd.random() < 0.40,
        "ano": rnd.randrange(1970, 2020),
        "mes": rnd.randrange(1, 13),
        "dia": rnd.randrange(1, 29),
        "tem_data": rnd.random() < 0.55,
        "tipo_log": tipo,
        "logradouro": rnd.choice(LOGRADOUROS),
        "numero": rnd.randrange(10, 4000),
        "complemento": f"sala {rnd.randrange(1, 90)}" if rnd.random() < 0.35 else "",
    }


# ------------------------------------------------- entidade -> registro


def _nome_pf(rnd: random.Random, ent: dict, perfil: Perfil, intacto: bool) -> str:
    nome = ent["nome"]
    if intacto:
        return nome
    partes = nome.split()
    if rnd.random() < perfil.abrevia_meio and len(partes) > 2:
        partes = (
            [partes[0]]
            + [(p[0] + "." if p[0].isupper() and len(p) > 2 else p) for p in partes[1:-1]]
            + [partes[-1]]
        )
    if rnd.random() < 0.30:
        partes = [p for p in partes if p.lower() not in ("de", "da", "do", "dos", "das")]
    if rnd.random() < 0.18 and len(partes) > 2:
        partes = partes[:-1]
    nome = " ".join(partes)
    if rnd.random() < perfil.inverte_ordem:
        pedacos = nome.split()
        if len(pedacos) > 1:
            nome = f"{pedacos[-1]}, {' '.join(pedacos[:-1])}"
    if rnd.random() < perfil.tira_acento:
        nome = sem_acento(nome)
    if rnd.random() < perfil.typos:
        nome = _typo(rnd, nome)
    if rnd.random() < perfil.typos_extra:
        nome = _typo(rnd, nome)
    caixa = rnd.random()
    if caixa < 0.30:
        nome = nome.upper()
    elif caixa < 0.45:
        nome = nome.lower()
    return nome


def _nome_pj(rnd: random.Random, ent: dict, perfil: Perfil, intacto: bool) -> str:
    if intacto:
        return ent["nome"]
    if rnd.random() < 0.10:
        # Cadastro preenchido com o nome fantasia. So os outros campos salvam.
        return ent["fantasia"].upper()
    nome = ent["nome"]
    trocas = {
        "LTDA": rnd.choice(("LTDA.", "LIMITADA", "")),
        "S/A": rnd.choice(("S.A.", "SA", "SOCIEDADE ANONIMA")),
        "ME": rnd.choice(("M.E.", "MICROEMPRESA", "")),
        "EIRELI": rnd.choice(("EIRELI.", "")),
        "EPP": rnd.choice(("E.P.P.", "")),
    }
    nome = nome.replace(ent["sufixo"], trocas[ent["sufixo"]]).strip()
    if rnd.random() < 0.45:
        nome = nome.replace(" & ", rnd.choice((" E ", " e ", "&")))
    if rnd.random() < perfil.tira_acento:
        nome = sem_acento(nome)
    if rnd.random() < perfil.typos:
        nome = _typo(rnd, nome)
    caixa = rnd.random()
    if caixa < 0.55:
        nome = nome.upper()
    elif caixa < 0.70:
        nome = nome.title()
    return " ".join(nome.split())


def _registro(rnd: random.Random, ent: dict, perfil: Perfil, primeiro: bool) -> dict:
    """Materializa uma leitura do cadastro. `primeiro` e o registro canonico."""
    intacto = primeiro or rnd.random() < perfil.nome_intacto
    nome = (_nome_pj if perfil.pj else _nome_pf)(rnd, ent, perfil, intacto)

    cidade = ent["cidade"]
    if not primeiro:
        if rnd.random() < 0.45:
            cidade = sem_acento(cidade)
        if rnd.random() < perfil.campo_ausente * 0.5:
            cidade = ""
    uf = ent["uf"] if cidade or rnd.random() < 0.5 else ""

    telefone = _formatar_telefone(rnd, ent["ddd"], ent["fone"])
    if not primeiro:
        if rnd.random() < perfil.campo_ausente:
            telefone = ""
        elif rnd.random() < 0.08:
            digitos = list(ent["fone"])
            i = rnd.randrange(len(digitos))
            digitos[i] = str((int(digitos[i]) + 1) % 10)
            telefone = _formatar_telefone(rnd, ent["ddd"], "".join(digitos))

    email = f"{ent['local_email']}{ent['num_email']}@{ent['dominio']}"
    if not primeiro:
        if rnd.random() < perfil.campo_ausente + 0.20:
            email = ""
        elif rnd.random() < 0.22:
            email = f"{ent['local_email']}{ent['num_email']}@{rnd.choice(DOMINIOS)}"

    documento = ""
    if ent["tem_doc"] and (primeiro or rnd.random() > perfil.campo_ausente + 0.35):
        documento = _formatar_documento(rnd, ent["doc"], perfil.pj)

    nascimento = ""
    if ent["tem_data"] and (primeiro or rnd.random() > perfil.campo_ausente):
        nascimento = _formatar_data(rnd, ent["ano"], ent["mes"], ent["dia"])

    tipo = ent["tipo_log"]
    if not primeiro and rnd.random() < 0.55:
        tipo = dict(TIPOS_LOGRADOURO)[tipo]
    partes_end = [f"{tipo} {ent['logradouro']}", str(ent["numero"])]
    if ent["complemento"] and (primeiro or rnd.random() < 0.5):
        partes_end.append(ent["complemento"])
    endereco = ", ".join(partes_end)
    if not primeiro:
        if rnd.random() < 0.40:
            endereco = sem_acento(endereco)
        if rnd.random() < perfil.campo_ausente * 0.6:
            endereco = ""

    return {
        "nome": " ".join(nome.split()),
        "cidade": cidade,
        "uf": uf,
        "telefone": telefone,
        "email": email,
        "documento": documento,
        "nascimento": nascimento,
        "endereco": endereco,
    }


# --------------------------------------------------------- adversarios


def _homonimo(rnd: random.Random, ent: dict, perfil: Perfil) -> dict:
    """Outra pessoa com o MESMO nome e a MESMA cidade.

    Telefone, documento e data sao redesenhados; a data e forcada a existir dos
    dois lados para que o par seja resoluvel. Sem isso o alvo cobraria uma
    distincao que a evidencia disponivel nao permite fazer.
    """
    outra = (_entidade_pj if perfil.pj else _entidade_pf)(rnd)
    outra["nome"] = ent["nome"]
    if perfil.pj:
        outra["fantasia"] = ent["fantasia"]
        outra["sufixo"] = ent["sufixo"]
    outra["cidade"] = ent["cidade"]
    outra["uf"] = ent["uf"]
    outra["tem_data"] = True
    outra["ano"] = ent["ano"] + rnd.randrange(3, 25)
    outra["dia"] = 1 + (ent["dia"] + rnd.randrange(1, 27)) % 28
    return outra


def _quase_homonimo(rnd: random.Random, ent: dict, perfil: Perfil) -> dict:
    """Nome a uma ou duas letras de distancia, mesma cidade. O falso positivo
    que a similaridade aproximada compra junto com o recall."""
    outra = (_entidade_pj if perfil.pj else _entidade_pf)(rnd)
    outra["nome"] = _typo(rnd, ent["nome"])
    if perfil.pj:
        outra["fantasia"] = ent["fantasia"]
        outra["sufixo"] = ent["sufixo"]
    outra["cidade"] = ent["cidade"]
    outra["uf"] = ent["uf"]
    outra["tem_data"] = True
    outra["ano"] = ent["ano"] + rnd.randrange(2, 20)
    outra["tem_doc"] = True
    ent["tem_doc"] = True
    return outra


def _domicilio(rnd: random.Random, ent: dict, perfil: Perfil) -> dict:
    """Mesmo telefone e mesmo endereco, pessoas (ou filiais) diferentes.

    Existe para punir quem trata telefone igual como prova suficiente. O nome
    difere de forma decisiva, entao o par continua resoluvel.
    """
    outra = (_entidade_pj if perfil.pj else _entidade_pf)(rnd)
    outra["ddd"] = ent["ddd"]
    outra["fone"] = ent["fone"]
    outra["cidade"] = ent["cidade"]
    outra["uf"] = ent["uf"]
    outra["tipo_log"] = ent["tipo_log"]
    outra["logradouro"] = ent["logradouro"]
    outra["numero"] = ent["numero"]
    if not perfil.pj:
        # Mesma familia: o sobrenome coincide, o prenome nao.
        outra["nome"] = f"{rnd.choice(PRENOMES)} {ent['nome'].split()[-1]}"
    return outra


# ----------------------------------------------------------- montagem


def _construir(perfil: Perfil) -> tuple[list[dict], list[list[str]]]:
    rnd = random.Random(perfil.seed)
    fabrica = _entidade_pj if perfil.pj else _entidade_pf
    clusters: list[list[dict]] = []

    def cluster(ent: dict, tamanho: int) -> None:
        clusters.append([_registro(rnd, ent, perfil, i == 0) for i in range(tamanho)])

    for tamanho, quantos in (
        (2, perfil.clusters_2),
        (3, perfil.clusters_3),
        (4, perfil.clusters_4),
    ):
        for _ in range(quantos):
            cluster(fabrica(rnd), tamanho)

    for construtor, quantos in (
        (_homonimo, perfil.homonimos),
        (_quase_homonimo, perfil.quase_homonimos),
        (_domicilio, perfil.domicilios),
    ):
        for _ in range(quantos):
            base = fabrica(rnd)
            adversario = construtor(rnd, base, perfil)
            cluster(base, 1)
            cluster(adversario, 1)

    for _ in range(perfil.singletons):
        cluster(fabrica(rnd), 1)

    # Embaralhar ANTES de atribuir id: o id passa a ser um rotulo opaco. Se os
    # ids fossem dados na ordem de construcao, "ids vizinhos" seria um atalho
    # perfeito para o gabarito e o alvo mediria leitura de indice, nao linkage.
    achatado = [(i, reg) for i, grupo in enumerate(clusters) for reg in grupo]
    rnd.shuffle(achatado)

    prefixo = "PJ" if perfil.pj else "PF"
    registros: list[dict] = []
    por_cluster: dict[int, list[str]] = {}
    for pos, (idx, reg) in enumerate(achatado):
        rid = f"{prefixo}-{pos:06d}"
        registros.append({"id": rid, **reg})
        por_cluster.setdefault(idx, []).append(rid)

    pares = []
    for ids in por_cluster.values():
        ids = sorted(ids)
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                pares.append([ids[a], ids[b]])
    pares.sort()
    return registros, pares


# ------------------------------------------------------- banco do gate


def _gate_bank() -> list[dict]:
    """Registros pequenos e deformados. Nao decidem acerto: decidem contrato.

    Metade e cadastro normal (para o candidato ter o que casar) e metade e
    borda: nome vazio, campo so com espaco, unicode combinante, string longa,
    e dois registros identicos em tudo menos no id. Nada aqui tem gabarito —
    neste alvo `correct` significa "respeitou o contrato", nao "acertou".
    """
    rnd = random.Random(4199)
    perfil = Perfil(
        "gate",
        seed=4199,
        singletons=0,
        clusters_2=0,
        clusters_3=0,
        clusters_4=0,
        homonimos=0,
        quase_homonimos=0,
        domicilios=0,
    )
    registros: list[dict] = []
    for _ in range(80):
        ent = _entidade_pf(rnd)
        registros.append(_registro(rnd, ent, perfil, True))
        if rnd.random() < 0.5:
            registros.append(_registro(rnd, ent, perfil, False))

    vazio = {
        "nome": "",
        "cidade": "",
        "uf": "",
        "telefone": "",
        "email": "",
        "documento": "",
        "nascimento": "",
        "endereco": "",
    }
    bordas = [
        dict(vazio),
        dict(vazio, nome="   "),
        dict(vazio, nome="Ana", cidade="São Paulo"),
        dict(vazio, nome="ANA", cidade="Sao Paulo"),
        dict(vazio, nome="José" + "́", cidade="Niterói"),  # acento combinante
        dict(vazio, nome="José", cidade="Niteroi"),
        dict(vazio, nome="X" * 400, endereco="Y" * 400),
        dict(vazio, nome="X" * 400, endereco="Y" * 400),
        dict(vazio, nome="李 明", cidade="São Paulo"),
        dict(vazio, telefone="(11) 90000-0000"),
        dict(vazio, telefone="+55 11 90000-0000"),
        dict(vazio, nome="Maria, da Silva", cidade="Recife"),
        dict(vazio, nome="da Silva, Maria", cidade="Recife"),
    ]
    registros.extend(bordas)
    rnd.shuffle(registros)
    return [{"id": f"GT-{i:05d}", **reg} for i, reg in enumerate(registros)]


# ------------------------------------------------------------- asercoes


def _normalizar_ingenuo(texto: str) -> str:
    return " ".join(texto.lower().split())


def _f1_ingenuo(registros: list[dict], pares: list[list[str]]) -> float:
    """F1 da estrategia do seed: igualdade de nome normalizado, nada mais."""
    grupos: dict[str, list[str]] = {}
    for reg in registros:
        chave = _normalizar_ingenuo(reg["nome"])
        if chave:
            grupos.setdefault(chave, []).append(reg["id"])
    previstos = set()
    for ids in grupos.values():
        ordenados = sorted(ids)
        for a in range(len(ordenados)):
            for b in range(a + 1, len(ordenados)):
                previstos.add((ordenados[a], ordenados[b]))
    verdade = {(a, b) for a, b in pares}
    tp = len(previstos & verdade)
    if not tp:
        return 0.0
    precisao = tp / len(previstos)
    recall = tp / len(verdade)
    return 2 * precisao * recall / (precisao + recall)


def _tokens(texto: str) -> set[str]:
    return {t for t in sem_acento(texto).lower().replace(",", " ").split() if len(t) > 2}


def _digitos(texto: str) -> str:
    return "".join(c for c in texto if c.isdigit())


def _assert_banco_tem_dentes(nome: str, registros: list[dict], pares: list[list[str]]) -> None:
    """Recusa um banco que nao serve como alvo, por dois motivos opostos.

    O primeiro e a Falha 3: se a estrategia ingenua ja marca alto, nao ha
    headroom para distribuir em movimentos e a ablacao nao consegue separar
    braco nenhum. O segundo e o inverso e mais silencioso: se os pares
    positivos nao compartilham nenhum sinal recuperavel, o teto de F1 e baixo
    por construcao e a busca vai bater num muro que parece platô de dificuldade
    mas e defeito do dataset.
    """
    f1 = _f1_ingenuo(registros, pares)
    if f1 > 0.50:
        raise AssertionError(
            f"{nome}: a estrategia ingenua ja marca F1={f1:.3f}. Sobra headroom demais "
            "pouco: aumente a corrupcao de nome (nome_intacto menor) ou os homonimos."
        )
    if f1 < 0.08:
        raise AssertionError(
            f"{nome}: a estrategia ingenua marca F1={f1:.3f}, perto de zero. O seed "
            "precisa de um ponto de partida com sinal; media geometrica com um banco "
            "em ~0 apaga o score inteiro."
        )

    indice = {reg["id"]: reg for reg in registros}
    alcancaveis = 0
    for a, b in pares:
        ra, rb = indice[a], indice[b]
        tem_token = bool(_tokens(ra["nome"]) & _tokens(rb["nome"]))
        tem_fone = bool(_digitos(ra["telefone"])) and (
            _digitos(ra["telefone"])[-8:] == _digitos(rb["telefone"])[-8:]
        )
        tem_email = bool(ra["email"]) and ra["email"].lower() == rb["email"].lower()
        tem_doc = bool(_digitos(ra["documento"])) and (
            _digitos(ra["documento"]) == _digitos(rb["documento"])
        )
        if tem_token or tem_fone or tem_email or tem_doc:
            alcancaveis += 1
    fracao = alcancaveis / len(pares)
    if fracao < 0.80:
        raise AssertionError(
            f"{nome}: so {fracao:.1%} dos pares positivos compartilham algum sinal "
            "recuperavel (token de nome, telefone, email ou documento). O teto de F1 "
            "seria baixo por construcao — reduza a corrupcao."
        )

    posicao = {reg["id"]: i for i, reg in enumerate(registros)}
    vizinhos = sum(1 for a, b in pares if abs(posicao[a] - posicao[b]) <= 2)
    if vizinhos / len(pares) > 0.05:
        raise AssertionError(
            f"{nome}: {vizinhos / len(pares):.1%} dos pares positivos estao a menos de "
            "tres posicoes de distancia. O embaralhamento falhou e a ordem virou atalho."
        )


# ------------------------------------------------------------ escrita


def _escrever(path: Path, dados) -> None:
    path.write_text(json.dumps(dados, ensure_ascii=False, indent=None) + "\n", encoding="utf-8")


_CACHE: dict[str, tuple[list[dict], list[list[str]]]] = {}


def _banco(perfil: Perfil):
    if perfil.nome not in _CACHE:
        registros, pares = _construir(perfil)
        _assert_banco_tem_dentes(perfil.nome, registros, pares)
        _CACHE[perfil.nome] = (registros, pares)
    return _CACHE[perfil.nome]


def specs() -> list[datakit.DatasetSpec]:
    saida: list[datakit.DatasetSpec] = []
    for perfil in PERFIS:
        registros, pares = _banco(perfil)
        saida.append(
            datakit.DatasetSpec(
                f"records_{perfil.nome}.json",
                lambda p, perfil=perfil: _escrever(p, _banco(perfil)[0]),
                purpose=f"banco {perfil.nome}: registros SEM rotulo, o que match() recebe",
                rows=len(registros),
            )
        )
        saida.append(
            datakit.DatasetSpec(
                f"labels_{perfil.nome}.json",
                lambda p, perfil=perfil: _escrever(p, _banco(perfil)[1]),
                purpose=f"gabarito de {perfil.nome}: pares verdadeiros. So o avaliador le",
                rows=len(pares),
            )
        )
    gate = _gate_bank()
    saida.append(
        datakit.DatasetSpec(
            "gate_bank.json",
            lambda p: _escrever(p, _gate_bank()),
            purpose="UNICO banco que decide correcao: forma, determinismo, pureza, orcamento",
            rows=len(gate),
        )
    )
    return saida


def main() -> int:
    report = datakit.generate(HERE, specs(), force="--force" in sys.argv)
    print(f"dedupe_match: {report.render()}")
    for perfil in PERFIS:
        registros, pares = _banco(perfil)
        print(
            f"  {perfil.nome:9} {len(registros):5d} registros, {len(pares):4d} pares "
            f"positivos, F1 ingenuo {_f1_ingenuo(registros, pares):.3f}"
        )
    ok, detail = datakit.verify_lock(HERE)
    print(f"lock: {detail}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
