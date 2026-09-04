"""Gera os bancos SQLite congelados do target sql_workload.

Dois arquivos, dois papeis que nao se misturam — a mesma separacao do etl_agg e
do sql_agg, pela mesma razao (Falha 1):

  perf_loja.sqlite  -> so mede tempo. Grande o bastante para que um plano ruim
      custe centenas de milissegundos e um plano bom continue acima do piso de
      ruido. O conteudo e banal de proposito: nada aqui decide correcao.

  gate_loja.sqlite  -> decide `correct`, e so ele. Minusculo e montado linha a
      linha para que cada leitura errada plausivel de cada um dos OITO
      relatorios produza um result set diferente.

## O que este alvo tem de diferente dos outros

Os cinco alvos anteriores tem UM artefato para otimizar. Este tem NOVE: oito
consultas independentes mais o esquema fisico compartilhado por elas. A razao
esta em `docs/TARGET_DESIGN.md` §3e — um alvo cujo espaco uma sessao esgota em
cem segundos nao consegue comparar arquiteturas de busca, e todos os cinco
alvos anteriores tem esse defeito.

O mecanismo que fecha esse buraco aqui e a lei de Amdahl aplicada de proposito:
as oito consultas custam aproximadamente O MESMO no seed. Consertar uma delas
move o total em ~7%; o ganho cheio exige as oito, mais o subconjunto certo de
indices. Nao existe primeiro movimento que capture o headroom.

## Quais indices o banco ja traz, e quais NAO

Ja vem: as chaves primarias, `order_items(order_id)` e o UNIQUE de
`refunds(order_id)`. Sao os indices que qualquer esquema de producao teria no
dia zero — sem eles as subconsultas correlacionadas do seed virariam varredura
completa por pedido, e o headroom seria de duas ordens de grandeza concentrado
num movimento so (Falha 3).

NAO vem: nada em `orders` alem da PK. Nem `status`, nem `order_date`, nem
`customer_id`, nem `channel`, nem `ship_country`. Cinco colunas que as oito
consultas filtram de jeitos diferentes, e e dai que sai o joelho combinatorio do
alvo: o indice util para q1 nao e o util para q4, e cada indice criado e
cronometrado no regime frio.

## O detalhe que faz os indices valerem alguma coisa: a linha larga

`orders` tem doze colunas, das quais nenhuma consulta usa mais que seis. Numa
tabela estreita, varrer as linhas custa quase o mesmo que percorrer um indice
sobre elas, e criar indice nunca compensa dentro de um relatorio — o alvo
ensinaria "nunca crie indice", que e a licao errada. Com a linha larga a
varredura le dezenas de MB de paginas de dados e um indice cobrindo le menos de
um MB. A folga entre esses dois numeros e o movimento.

## Duas propriedades que sao CONTRATO, nao acidente de geracao

`docs/TARGET_DESIGN.md` §3c manda enumerar o que o banco de gate e o de
performance compartilham por acidente e decidir, um a um, se vira contrato
declarado ou se o gerador o quebra. As duas que importam aqui:

  1. `status` e SEMPRE minusculo. Declarado em `kb/00-contrato.md`. Sem isso,
     trocar `upper(o.status) = 'DELIVERED'` por `o.status = 'delivered'` — que e
     o movimento que destrava o indice de q1 — seria uma suposicao sobre este
     dado, nao uma reescrita valida.
  2. `order_date` e SEMPRE 'YYYY-MM-DD', dez caracteres, sem hora. Declarado
     tambem. Sem isso, trocar `strftime('%Y-%m-%d', o.order_date) >= :d0` por
     `o.order_date >= :d0` seria a mesma suposicao.

As duas sao verificadas pelo gerador nos DOIS bancos (`_assert_contrato`), para
que a declaracao da KB nao possa ficar mentindo depois de uma edicao aqui.

## Por que o dinheiro e INTEGER em centavos

Somar `REAL` em SQL e uma armadilha para um gate por igualdade: `SUM` sobre
ponto flutuante depende da ordem em que o planejador visita as linhas, e a ordem
muda quando o candidato cria um indice. O gate reprovaria uma otimizacao
legitima pelo ultimo bit da mantissa. Com `INTEGER`, `SUM` e exato e
independente de ordem.
"""

from __future__ import annotations

import random
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from labkit import datakit  # noqa: E402

PERF_DB = "perf_loja.sqlite"
GATE_DB = "gate_loja.sqlite"

REGIOES = ("norte", "nordeste", "centro-oeste", "sudeste", "sul")
SEGMENTOS = ("varejo", "atacado", "corporativo")
CANAIS = ("web", "app", "loja", "parceiro")
PAISES = ("BR", "BR", "BR", "AR", "CL", "UY", "PY")
STATUS = ("delivered", "delivered", "delivered", "delivered", "pending", "cancelled", "returned")
CATEGORIAS = ("bebida", "mercearia", "limpeza", "higiene", "hortifruti", "padaria")
MARCAS = ("aurora", "boreal", "cume", "delta", "estiva", "farol", "grao", "horizonte")
ARMAZENS = ("SP01", "SP02", "RJ01", "MG01", "PR01", "PE01")

ESQUEMA = """
CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    region      TEXT,
    segment     TEXT NOT NULL,
    signup_date TEXT NOT NULL,
    email       TEXT NOT NULL,
    phone       TEXT NOT NULL,
    notes       TEXT NOT NULL
);

CREATE TABLE orders (
    order_id      INTEGER PRIMARY KEY,
    customer_id   INTEGER NOT NULL,
    order_date    TEXT NOT NULL,
    status        TEXT NOT NULL,
    channel       TEXT NOT NULL,
    ship_country  TEXT NOT NULL,
    coupon        TEXT,
    freight_cents INTEGER NOT NULL,
    weight_g      INTEGER NOT NULL,
    warehouse     TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    notes         TEXT NOT NULL
);

CREATE TABLE order_items (
    item_id    INTEGER PRIMARY KEY,
    order_id   INTEGER NOT NULL,
    sku        TEXT NOT NULL,
    qty        INTEGER NOT NULL,
    unit_cents INTEGER NOT NULL
);

CREATE TABLE refunds (
    refund_id    INTEGER PRIMARY KEY,
    order_id     INTEGER NOT NULL UNIQUE,
    amount_cents INTEGER NOT NULL,
    refund_date  TEXT NOT NULL
);

CREATE TABLE products (
    sku        TEXT PRIMARY KEY,
    category   TEXT NOT NULL,
    brand      TEXT NOT NULL,
    cost_cents INTEGER NOT NULL
);

CREATE INDEX ix_items_order ON order_items(order_id);
"""


def _connect_fresh(path: Path) -> sqlite3.Connection:
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    conn.executescript(ESQUEMA)
    return conn


def _finish(conn: sqlite3.Connection) -> None:
    conn.commit()
    conn.execute("VACUUM")
    conn.commit()
    conn.close()


def _dia(base_ord: int, offset: int) -> str:
    import datetime

    return datetime.date.fromordinal(base_ord + offset).isoformat()


# ------------------------------------------------------------------ performance

#: Padding da linha de `orders`. Ver o docstring: sem a linha larga o indice
#: nunca se paga e o alvo ensinaria a licao errada.
NOTA_PADRAO = (
    "pedido registrado pelo fluxo padrao; conferencia fiscal pendente; "
    "observacoes do operador nao se aplicam a este registro"
)


def _build_perf(path: Path, n_customers: int, n_orders: int, seed: int) -> None:
    import datetime

    rng = random.Random(seed)
    base = datetime.date(2023, 1, 1).toordinal()
    dias = 730

    conn = _connect_fresh(path)

    produtos = []
    for i in range(700):
        sku = f"SKU{i:05d}"
        produtos.append(
            (sku, CATEGORIAS[i % len(CATEGORIAS)], MARCAS[i % len(MARCAS)], rng.randint(80, 9000))
        )
    conn.executemany("INSERT INTO products VALUES (?,?,?,?)", produtos)

    clientes = []
    for cid in range(1, n_customers + 1):
        # 1 em 40 sem regiao: a coluna e NULLable de verdade, e COALESCE para
        # 'sem_regiao' faz parte do contrato de q3 e q4.
        regiao = None if cid % 40 == 0 else REGIOES[cid % len(REGIOES)]
        clientes.append(
            (
                cid,
                f"cliente {cid:05d}",
                regiao,
                SEGMENTOS[cid % len(SEGMENTOS)],
                _dia(base, -rng.randint(0, 900)),
                f"c{cid}@exemplo.com.br",
                f"+55 11 9{cid:08d}",
                "cadastro migrado do sistema anterior; revisar telefone",
            )
        )
    conn.executemany("INSERT INTO customers VALUES (?,?,?,?,?,?,?,?)", clientes)

    pedidos = []
    itens = []
    estornos = []
    item_id = 0
    refund_id = 0
    for oid in range(1, n_orders + 1):
        # Cliente com cauda: 20% dos clientes concentram metade dos pedidos.
        if rng.random() < 0.5:
            cid = rng.randint(1, max(1, n_customers // 5))
        else:
            cid = rng.randint(1, n_customers)
        data = _dia(base, rng.randint(0, dias - 1))
        status = STATUS[rng.randrange(len(STATUS))]
        pedidos.append(
            (
                oid,
                cid,
                data,
                status,
                CANAIS[rng.randrange(len(CANAIS))],
                PAISES[rng.randrange(len(PAISES))],
                f"CUPOM{rng.randint(1, 60):03d}" if rng.random() < 0.25 else None,
                rng.randint(0, 4500),
                rng.randint(100, 25000),
                ARMAZENS[rng.randrange(len(ARMAZENS))],
                data + "T03:00:00Z",
                NOTA_PADRAO,
            )
        )
        # 1 em 60 pedido entregue sem item nenhum: bruto zero e legitimo.
        n_itens = 0 if oid % 60 == 0 else rng.randint(1, 5)
        for _ in range(n_itens):
            item_id += 1
            itens.append(
                (
                    item_id,
                    oid,
                    produtos[rng.randrange(len(produtos))][0],
                    rng.randint(1, 6),
                    rng.randint(150, 12000),
                )
            )
        if status == "delivered" and rng.random() < 0.09:
            refund_id += 1
            estornos.append((refund_id, oid, rng.randint(100, 30000), data))

    conn.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", pedidos)
    conn.executemany("INSERT INTO order_items VALUES (?,?,?,?,?)", itens)
    conn.executemany("INSERT INTO refunds VALUES (?,?,?,?)", estornos)
    _finish(conn)
    _assert_contrato(path, PERF_DB)
    _assert_perf_tem_volume(path)


# ------------------------------------------------------------------------ gate

#: SKUs do banco de gate. `SKU-D` nunca e vendido: um produto sem venda nao pode
#: aparecer no relatorio de q2, e so um `LEFT JOIN` frouxo o faria aparecer.
#: `SKU-E` empata em receita com `SKU-C` para que a ordem de desempate de q2
#: (receita DESC, sku) seja verificavel. O pedido 4 tem DUAS linhas do mesmo
#: SKU-A: sem isso, `COUNT(*)` e `COUNT(DISTINCT order_id)` dariam o mesmo numero
#: em q2 e o mutante passaria.
GATE_PRODUTOS = [
    ("SKU-A", "bebida", "aurora", 400),
    ("SKU-B", "mercearia", "boreal", 900),
    ("SKU-C", "limpeza", "cume", 300),
    ("SKU-D", "higiene", "delta", 250),
    ("SKU-E", "bebida", "estiva", 700),
]

#: (id, nome, regiao, segmento, signup)
#: c2 e c9 tem `region` NULL — o contrato manda apresentar 'sem_regiao'.
#: c5 nunca comprou; c6 so tem pedido nao entregue; c8 so tem pedido na borda
#: superior EXCLUSIVA da janela. Os tres sao a resposta de q4, e cada um por um
#: motivo diferente. c11 assinou DEPOIS da janela e por isso NAO entra.
GATE_CLIENTES = [
    (1, "cliente um", "sul", "varejo", "2022-03-01"),
    (2, "cliente dois", None, "atacado", "2022-05-14"),
    (3, "cliente tres", "sul", "varejo", "2022-07-30"),
    (4, "cliente quatro", "norte", "corporativo", "2021-11-02"),
    (5, "cliente cinco", "norte", "varejo", "2023-01-09"),
    (6, "cliente seis", "sudeste", "atacado", "2023-02-18"),
    (7, "cliente sete", "sudeste", "varejo", "2022-09-25"),
    (8, "cliente oito", "sul", "corporativo", "2023-04-04"),
    (9, "cliente nove", None, "varejo", "2023-06-11"),
    (10, "cliente dez", "norte", "atacado", "2023-08-21"),
    (11, "cliente onze", "sul", "varejo", "2024-06-01"),
]

#: (order_id, customer_id, order_date, status, channel, ship_country)
GATE_PEDIDOS = [
    (1, 1, "2024-01-15", "delivered", "web", "BR"),
    (2, 1, "2024-02-10", "delivered", "app", "AR"),
    (3, 3, "2024-01-20", "delivered", "web", "BR"),
    (4, 2, "2024-03-05", "delivered", "loja", "BR"),
    (5, 4, "2024-02-02", "delivered", "parceiro", "AR"),
    (6, 6, "2024-01-10", "cancelled", "web", "BR"),
    (7, 7, "2024-01-01", "delivered", "web", "BR"),
    (8, 8, "2024-04-01", "delivered", "web", "BR"),
    (9, 9, "2024-02-14", "delivered", "app", "UY"),
    (10, 9, "2024-02-14", "delivered", "web", "BR"),
    (11, 10, "2024-03-20", "delivered", "loja", "PY"),
    (12, 1, "2024-02-20", "delivered", "app", "AR"),
    (13, 4, "2024-03-15", "delivered", "app", "AR"),
    (14, 2, "2024-02-28", "pending", "web", "BR"),
    (15, 3, "2024-03-01", "delivered", "loja", "BR"),
    (16, 7, "2023-12-31", "delivered", "web", "BR"),
    (17, 9, "2024-01-05", "cancelled", "web", "BR"),
    (18, 6, "2024-03-10", "returned", "parceiro", "BR"),
]

#: (order_id, sku, qty, unit_cents). O pedido 12 esta entregue e NAO aparece
#: aqui: pedido entregue sem item nenhum tem bruto zero e continua contando como
#: pedido — e a diferenca entre `COUNT(*)` e `COUNT(DISTINCT ...)` sobre um
#: `JOIN` que descarta a linha.
GATE_ITENS = [
    (1, "SKU-A", 2, 2500),
    (1, "SKU-B", 1, 5000),
    (2, "SKU-A", 1, 3000),
    (3, "SKU-C", 3, 2000),
    (4, "SKU-A", 4, 1000),
    (4, "SKU-A", 2, 500),
    (5, "SKU-B", 2, 3500),
    (5, "SKU-E", 1, 9900),
    (6, "SKU-B", 5, 1000),
    (7, "SKU-A", 1, 9000),
    (8, "SKU-B", 1, 8000),
    (9, "SKU-C", 2, 1200),
    (10, "SKU-A", 1, 2600),
    (11, "SKU-B", 1, 3000),
    (13, "SKU-C", 1, 1500),
    (14, "SKU-A", 10, 9999),
    (15, "SKU-B", 1, 4500),
    (16, "SKU-A", 1, 7000),
    (17, "SKU-C", 1, 500),
    (18, "SKU-A", 1, 700),
]

#: (order_id, amount_cents, refund_date). As duas datas de estorno divergem da
#: data do pedido de proposito, e a do pedido 11 cai FORA da janela: o estorno e
#: atribuido ao dia do PEDIDO, nunca ao dia do estorno. Um relatorio que agrupa
#: por `refund_date` da outro numero, e so este banco enxerga isso.
GATE_ESTORNOS = [
    (1, 2500, "2024-01-31"),
    (11, 5000, "2024-04-10"),
]


def _build_gate(path: Path) -> None:
    conn = _connect_fresh(path)
    conn.executemany("INSERT INTO products VALUES (?,?,?,?)", GATE_PRODUTOS)
    conn.executemany(
        "INSERT INTO customers VALUES (?,?,?,?,?,?,?,?)",
        [
            (cid, nome, regiao, seg, signup, f"c{cid}@gate.test", f"+55 11 900{cid:05d}", "-")
            for cid, nome, regiao, seg, signup in GATE_CLIENTES
        ],
    )
    conn.executemany(
        "INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                oid,
                cid,
                data,
                status,
                canal,
                pais,
                None if oid % 3 else f"CUPOM{oid:03d}",
                100 * oid,
                1000 + oid,
                ARMAZENS[oid % len(ARMAZENS)],
                data + "T03:00:00Z",
                "linha de gate",
            )
            for oid, cid, data, status, canal, pais in GATE_PEDIDOS
        ],
    )
    conn.executemany(
        "INSERT INTO order_items VALUES (?,?,?,?,?)",
        [(i + 1, oid, sku, qty, cents) for i, (oid, sku, qty, cents) in enumerate(GATE_ITENS)],
    )
    conn.executemany(
        "INSERT INTO refunds VALUES (?,?,?,?)",
        [(i + 1, oid, valor, data) for i, (oid, valor, data) in enumerate(GATE_ESTORNOS)],
    )
    _finish(conn)
    _assert_contrato(path, GATE_DB)
    _assert_gate_tem_dentes(path)


# ------------------------------------------------------------------- asserções

#: A janela que o gate usa como referencia para as checagens de dentes. E a
#: mesma do primeiro jogo de parametros de `eval.py`; se as duas divergirem, as
#: armadilhas plantadas aqui deixam de ser exercidas la.
JANELA_DENTES = ("2024-01-01", "2024-04-01")


def _assert_contrato(path: Path, rotulo: str) -> None:
    """As duas propriedades que a KB declara como CONTRATO do esquema (§3c).

    Sem elas, tornar os predicados sargaveis — que e o movimento que destrava o
    indice de q1 — seria uma suposicao sobre ESTE dado em vez de uma reescrita
    valida. Elas valem nos DOIS bancos, e sao verificadas nos dois, para que a
    declaracao da KB nao possa passar a mentir depois de uma edicao aqui.
    """
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        n = conn.execute("SELECT COUNT(*) FROM orders WHERE status <> lower(status)").fetchone()[0]
        if n:
            raise AssertionError(
                f"{rotulo}: {n} pedidos com `status` fora de minusculo. A KB declara que "
                "`status` e sempre minusculo, e e essa declaracao que torna "
                "`o.status = 'delivered'` uma reescrita valida de `upper(o.status) = 'DELIVERED'`."
            )
        n = conn.execute("SELECT COUNT(*) FROM orders WHERE length(order_date) <> 10").fetchone()[0]
        if n:
            raise AssertionError(
                f"{rotulo}: {n} pedidos com `order_date` fora de 'YYYY-MM-DD'. A KB declara o "
                "formato, e e essa declaracao que torna `o.order_date >= :d0` uma reescrita "
                "valida de `strftime('%Y-%m-%d', o.order_date) >= :d0`."
            )
        # Integridade referencial. Nao ha FK declarada no esquema, entao "todo
        # pedido tem cliente" e "todo item tem produto" seriam propriedades
        # compartilhadas por ACIDENTE de geracao entre os dois bancos — e §3c
        # manda decidir uma a uma: ou vira contrato declarado na KB, ou o gerador
        # do gate a quebra. Estas duas viraram contrato (kb/00-contrato.md), e e
        # esta assercao que impede a declaracao de comecar a mentir. Sem ela, uma
        # consulta que junta `customers` com INNER JOIN estaria certa por sorte.
        orfaos = conn.execute(
            "SELECT COUNT(*) FROM orders o WHERE NOT EXISTS "
            "(SELECT 1 FROM customers c WHERE c.customer_id = o.customer_id)"
        ).fetchone()[0]
        if orfaos:
            raise AssertionError(
                f"{rotulo}: {orfaos} pedidos sem cliente correspondente. A KB declara que todo "
                "`orders.customer_id` existe em `customers`, e e essa declaracao que torna um "
                "INNER JOIN com `customers` uma escrita valida."
            )
        orfaos = conn.execute(
            "SELECT COUNT(*) FROM order_items i WHERE NOT EXISTS "
            "(SELECT 1 FROM products p WHERE p.sku = i.sku)"
        ).fetchone()[0]
        if orfaos:
            raise AssertionError(
                f"{rotulo}: {orfaos} itens com SKU fora de `products`. A KB declara que todo "
                "`order_items.sku` existe em `products`."
            )
        n = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'index' AND tbl_name = 'orders' "
            "AND sql IS NOT NULL"
        ).fetchone()[0]
        if n:
            raise AssertionError(
                f"{rotulo}: ja existem {n} indices explicitos em `orders`. E de la que sai o "
                "espaco de busca deste alvo; entregar o indice pronto tira o movimento."
            )
    finally:
        conn.close()


def _assert_perf_tem_volume(path: Path) -> None:
    """O banco medido precisa dar trabalho as OITO consultas, nao a duas."""
    d0, d1 = JANELA_DENTES
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        checks = [
            (
                "pedidos entregues na janela",
                2000,
                f"SELECT COUNT(*) FROM orders WHERE status='delivered' "
                f"AND order_date >= '{d0}' AND order_date < '{d1}'",
            ),
            (
                "estornos de pedidos entregues",
                100,
                "SELECT COUNT(*) FROM refunds r JOIN orders o USING (order_id) "
                "WHERE o.status='delivered'",
            ),
            (
                "clientes sem pedido entregue na janela",
                50,
                f"SELECT COUNT(*) FROM customers c WHERE NOT EXISTS (SELECT 1 FROM orders o "
                f"WHERE o.customer_id=c.customer_id AND o.status='delivered' "
                f"AND o.order_date >= '{d0}' AND o.order_date < '{d1}')",
            ),
            (
                "pedidos entregues sem item",
                50,
                "SELECT COUNT(*) FROM orders o WHERE o.status='delivered' AND NOT EXISTS "
                "(SELECT 1 FROM order_items i WHERE i.order_id=o.order_id)",
            ),
            (
                "dias distintos com pedido na janela",
                80,
                f"SELECT COUNT(DISTINCT order_date) FROM orders "
                f"WHERE order_date >= '{d0}' AND order_date < '{d1}'",
            ),
            (
                "skus vendidos na janela",
                500,
                f"SELECT COUNT(DISTINCT i.sku) FROM order_items i JOIN orders o USING (order_id) "
                f"WHERE o.status='delivered' AND o.order_date >= '{d0}' AND o.order_date < '{d1}'",
            ),
        ]
        for rotulo, minimo, sql in checks:
            valor = conn.execute(sql).fetchone()[0]
            if valor < minimo:
                raise AssertionError(
                    f"{PERF_DB}: {rotulo} = {valor}, minimo {minimo}. Uma das oito consultas "
                    "ficaria sem trabalho e o headroom dela sumiria da media geometrica."
                )
    finally:
        conn.close()


def _assert_gate_tem_dentes(path: Path) -> None:
    """Prova que o banco de gate distingue os erros que ele deveria distinguir.

    Nao e decoracao: e a Falha 1 virada em codigo. Cada linha abaixo e a
    pre-condicao de um mutante de `eval.py`. Se uma delas sumir numa edicao das
    tabelas la em cima, o `--selftest` so reclamaria muito depois, com uma
    mensagem que nao aponta para ca.
    """
    d0, d1 = JANELA_DENTES
    liquido_por_cliente = f"""
        WITH bruto AS (
            SELECT o.order_id, o.customer_id,
                   COALESCE((SELECT SUM(i.qty*i.unit_cents) FROM order_items i
                             WHERE i.order_id = o.order_id), 0) AS bruto,
                   COALESCE((SELECT r.amount_cents FROM refunds r
                             WHERE r.order_id = o.order_id), 0) AS estorno
            FROM orders o
            WHERE o.status = 'delivered'
              AND o.order_date >= '{d0}' AND o.order_date < '{d1}'
        )
        SELECT COALESCE(c.region, 'sem_regiao') AS reg, b.customer_id,
               SUM(b.bruto) - SUM(b.estorno) AS liquido
        FROM bruto b JOIN customers c USING (customer_id)
        GROUP BY reg, b.customer_id
    """

    checks = [
        (
            "pedido entregue sem nenhum item (q1/q6/q8: bruto zero ainda conta como pedido)",
            "SELECT COUNT(*) FROM orders o WHERE o.status='delivered' AND NOT EXISTS "
            "(SELECT 1 FROM order_items i WHERE i.order_id=o.order_id) "
            f"AND o.order_date >= '{d0}' AND o.order_date < '{d1}'",
        ),
        (
            "pedido com mais de um item E estorno (armadilha de fan-out)",
            "SELECT COUNT(*) FROM (SELECT r.order_id FROM refunds r "
            "JOIN order_items i ON i.order_id=r.order_id "
            "GROUP BY r.order_id HAVING COUNT(*) > 1)",
        ),
        (
            "estorno maior que o bruto do pedido (liquido negativo)",
            "SELECT COUNT(*) FROM refunds r WHERE r.amount_cents > COALESCE("
            "(SELECT SUM(i.qty*i.unit_cents) FROM order_items i WHERE i.order_id=r.order_id), 0)",
        ),
        (
            "cliente com region NULL e pedido entregue (q3/q4 apresentam 'sem_regiao')",
            "SELECT COUNT(*) FROM customers c JOIN orders o USING (customer_id) "
            "WHERE c.region IS NULL AND o.status='delivered'",
        ),
        (
            "cliente sem nenhum pedido (q4)",
            "SELECT COUNT(*) FROM customers c WHERE NOT EXISTS "
            "(SELECT 1 FROM orders o WHERE o.customer_id=c.customer_id)",
        ),
        (
            "cliente com pedido mas nenhum entregue na janela (q4)",
            "SELECT COUNT(*) FROM customers c WHERE EXISTS "
            "(SELECT 1 FROM orders o WHERE o.customer_id=c.customer_id) AND NOT EXISTS "
            "(SELECT 1 FROM orders o WHERE o.customer_id=c.customer_id AND o.status='delivered' "
            f"AND o.order_date >= '{d0}' AND o.order_date < '{d1}')",
        ),
        (
            "pedido exatamente na borda inferior INCLUSIVA da janela",
            f"SELECT COUNT(*) FROM orders WHERE order_date = '{d0}' AND status='delivered'",
        ),
        (
            "pedido exatamente na borda superior EXCLUSIVA da janela",
            f"SELECT COUNT(*) FROM orders WHERE order_date = '{d1}' AND status='delivered'",
        ),
        (
            "dois pedidos entregues do mesmo cliente na mesma data (q7 desempata por order_id)",
            "SELECT COUNT(*) FROM (SELECT customer_id, order_date FROM orders "
            f"WHERE status='delivered' AND order_date >= '{d0}' AND order_date < '{d1}' "
            "GROUP BY customer_id, order_date HAVING COUNT(*) > 1)",
        ),
        (
            "pedido que casa canal E pais ao mesmo tempo (q5 nao pode duplica-lo)",
            "SELECT COUNT(*) FROM orders WHERE status='delivered' AND channel='app' "
            f"AND ship_country='AR' AND order_date >= '{d0}' AND order_date < '{d1}'",
        ),
        (
            "pedido que casa SO o pais (q5: o UNION precisa dos dois ramos)",
            "SELECT COUNT(*) FROM orders WHERE status='delivered' AND channel<>'app' "
            f"AND ship_country='AR' AND order_date >= '{d0}' AND order_date < '{d1}'",
        ),
        (
            "dia com pedido mas nenhum entregue (q8 emite linha zerada)",
            "SELECT COUNT(*) FROM (SELECT order_date FROM orders "
            f"WHERE order_date >= '{d0}' AND order_date < '{d1}' "
            "GROUP BY order_date HAVING SUM(status='delivered') = 0)",
        ),
        (
            "estorno com refund_date fora da janela do pedido (atribuicao pela data do PEDIDO)",
            "SELECT COUNT(*) FROM refunds r JOIN orders o USING (order_id) "
            f"WHERE o.order_date < '{d1}' AND r.refund_date >= '{d1}'",
        ),
        (
            "dois SKUs com receita identica na janela (q2 desempata por sku)",
            "SELECT COUNT(*) FROM (SELECT i.sku, SUM(i.qty*i.unit_cents) AS rec "
            "FROM order_items i JOIN orders o USING (order_id) WHERE o.status='delivered' "
            f"AND o.order_date >= '{d0}' AND o.order_date < '{d1}' "
            "GROUP BY i.sku HAVING rec IN (SELECT SUM(i2.qty*i2.unit_cents) "
            "FROM order_items i2 JOIN orders o2 ON o2.order_id=i2.order_id "
            "WHERE o2.status='delivered' "
            f"AND o2.order_date >= '{d0}' AND o2.order_date < '{d1}' "
            "GROUP BY i2.sku HAVING i2.sku <> i.sku))",
        ),
        (
            "pedido com duas linhas do MESMO sku (q2: COUNT(*) != COUNT(DISTINCT order_id))",
            "SELECT COUNT(*) FROM (SELECT order_id, sku FROM order_items "
            "GROUP BY order_id, sku HAVING COUNT(*) > 1)",
        ),
        (
            "produto sem nenhuma venda (q2 nao pode lista-lo)",
            "SELECT COUNT(*) FROM products p WHERE NOT EXISTS "
            "(SELECT 1 FROM order_items i WHERE i.sku = p.sku)",
        ),
        (
            "cliente cadastrado depois da janela e sem pedidos (q4 nao pode lista-lo)",
            f"SELECT COUNT(*) FROM customers c WHERE c.signup_date >= '{d1}' AND NOT EXISTS "
            "(SELECT 1 FROM orders o WHERE o.customer_id=c.customer_id)",
        ),
    ]

    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        for rotulo, sql in checks:
            linha = conn.execute(sql).fetchone()
            if linha is None or linha[0] < 1:
                raise AssertionError(
                    f"{GATE_DB} nao tem {rotulo}: o gate ficaria cego para o mutante "
                    "correspondente. Plante a linha nas tabelas GATE_* deste arquivo."
                )
        empates = conn.execute(
            f"WITH t AS ({liquido_por_cliente}) "
            "SELECT COUNT(*) FROM (SELECT reg, liquido FROM t "
            "GROUP BY reg, liquido HAVING COUNT(*) > 1)"
        ).fetchone()[0]
        if empates < 1:
            raise AssertionError(
                f"{GATE_DB} nao tem empate exato de liquido dentro de uma regiao: RANK e "
                "ROW_NUMBER produziriam o mesmo result set em q3 e o mutante passaria."
            )
    finally:
        conn.close()


# ------------------------------------------------------------------------ specs


def specs() -> list[datakit.DatasetSpec]:
    return [
        datakit.DatasetSpec(
            PERF_DB,
            lambda p: _build_perf(p, n_customers=3000, n_orders=120_000, seed=20260904),
            purpose=(
                "banco de performance: 24 meses, 120k pedidos largos, ~350k itens. So mede tempo."
            ),
            rows=120_000,
        ),
        datakit.DatasetSpec(
            GATE_DB,
            _build_gate,
            purpose=(
                "UNICO banco que decide correcao: bordas de data, empates, fan-out, NULLs, "
                "pedido sem item, estorno fora da janela, cliente sem pedido"
            ),
            rows=len(GATE_PEDIDOS),
        ),
    ]


def main() -> int:
    report = datakit.generate(HERE, specs(), force="--force" in sys.argv)
    print(f"sql_workload: {report.render()}")
    ok, detail = datakit.verify_lock(HERE)
    print(f"lock: {detail}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
