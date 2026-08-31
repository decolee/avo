"""Gera os bancos SQLite congelados do target sql_agg.

Dois arquivos, dois papéis que não se misturam — a mesma separação do etl_agg,
pela mesma razão (Falha 1):

  perf_shop.sqlite  -> só mede tempo. Grande o bastante para que um plano ruim
      custe centenas de milissegundos e um plano bom continue acima do piso de
      ruído. O conteúdo é banal de propósito: nada aqui precisa ser adversarial,
      porque nada aqui decide correção.

  gate_shop.sqlite  -> decide `correct`, e só ele. Minúsculo e desenhado linha a
      linha para que cada leitura errada plausível do contrato produza um result
      set diferente. Um banco "normal" não consegue fazer isso: pedidos sem
      item, estorno maior que a venda, empate exato de receita e datas
      exatamente na borda da janela não aparecem por acaso em dado sintético
      uniforme — precisam ser colocados à mão.

## Por que o dinheiro é INTEGER em centavos

Somar `REAL` em SQL é uma armadilha para um gate baseado em hash: `SUM` sobre
ponto flutuante depende da ordem em que o planejador visita as linhas, e a ordem
muda quando o candidato cria um índice. O gate reprovaria uma otimização
legítima pelo último bit da mantissa — reprovar candidato bom é tão danoso
quanto aprovar candidato ruim.

Com `INTEGER`, `SUM` é exato e independente de ordem. O único valor derivado com
ponto flutuante do contrato (`pct_estorno`) é calculado a partir de duas somas
inteiras já fechadas, então é uma expressão determinística sobre dois inteiros,
não uma acumulação. Essa é a decisão declarada em `kb/00-contrato.md`.

## Quais índices o banco já traz

Chaves primárias, `order_items(order_id)` e o índice implícito de
`refunds(order_id) UNIQUE`. São os índices que qualquer esquema de produção
teria no dia zero, e sem o de `order_items` a subconsulta correlacionada do seed
viraria um scan completo por pedido — headroom de duas ordens de grandeza
concentrado num único movimento, exatamente o defeito que este laboratório
existe para não repetir (Falha 3).

O que **não** vem pronto é índice em `orders`. É de lá que sai boa parte do
espaço de busca: filtrar por `status` e `order_date` sem índice custa varrer as
páginas de dados dos dois anos inteiros para achar um trimestre.

## Por que a tabela `orders` é larga

Doze colunas, das quais a consulta usa quatro. Não é enfeite: é o que decide se
um índice se paga. Numa tabela estreita, varrer 200 mil linhas custa pouco mais
que percorrer um índice sobre elas, e criar o índice nunca compensa dentro de um
relatório — o alvo ensinaria "nunca crie índice", que é a lição errada para
levar ao Postgres. Com a linha larga, a varredura lê dezenas de MB de páginas de
dados e um índice *cobrindo* as quatro colunas usadas lê menos de um MB. A folga
entre esses dois números é o que transforma "criar o índice certo" num movimento
de verdade, com custo e retorno mensuráveis.
"""

from __future__ import annotations

import random
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from labkit import datakit  # noqa: E402

PERF_DB = "perf_shop.sqlite"
GATE_DB = "gate_shop.sqlite"

REGIONS = ("Sudeste", "Sul", "Nordeste", "Norte", "Centro-Oeste", "Exterior")
SEGMENTS = ("varejo", "atacado", "assinatura", "marketplace")
CHANNELS = ("web", "app", "loja", "televendas", "b2b")

#: `delivered` é o único status que entra na apuração. Os outros existem porque
#: existem no mundo, e porque esquecer o filtro é um erro plausível — o gate tem
#: linhas plantadas para pegá-lo.
STATUSES = ("delivered",) * 8 + ("pending", "shipped", "cancelled", "returned")

PAYMENTS = ("cartao", "pix", "boleto", "carteira", "credito-loja")
CITIES = ("Sao Paulo", "Rio de Janeiro", "Belo Horizonte", "Curitiba", "Recife", "Porto Alegre")
UFS = ("SP", "RJ", "MG", "PR", "PE", "RS")
DEVICES = ("ios", "android", "desktop", "tablet")

SCHEMA = """
CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL,
    region      TEXT,
    segment     TEXT    NOT NULL,
    signup_date TEXT    NOT NULL
);

-- `orders` é larga de propósito: a consulta usa quatro colunas das doze. Ver a
-- nota do topo do arquivo — é essa largura que dá valor a um índice cobrindo.
CREATE TABLE orders (
    order_id       INTEGER PRIMARY KEY,
    customer_id    INTEGER NOT NULL REFERENCES customers(customer_id),
    order_date     TEXT    NOT NULL,
    status         TEXT    NOT NULL,
    channel        TEXT    NOT NULL,
    payment_method TEXT    NOT NULL,
    ship_city      TEXT    NOT NULL,
    ship_state     TEXT    NOT NULL,
    ship_zip       TEXT    NOT NULL,
    coupon_code    TEXT,
    device         TEXT    NOT NULL,
    note           TEXT    NOT NULL
);

CREATE TABLE order_items (
    item_id    INTEGER PRIMARY KEY,
    order_id   INTEGER NOT NULL REFERENCES orders(order_id),
    product_id INTEGER NOT NULL,
    qty        INTEGER NOT NULL,
    unit_cents INTEGER NOT NULL
);

CREATE TABLE refunds (
    refund_id   INTEGER PRIMARY KEY,
    order_id    INTEGER NOT NULL UNIQUE REFERENCES orders(order_id),
    amount_cents INTEGER NOT NULL,
    refund_date TEXT    NOT NULL
);

CREATE INDEX idx_order_items_order ON order_items(order_id);
"""

DAYS_IN_MONTH = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def _month_days(year: int, month: int) -> int:
    if month == 2 and (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)):
        return 29
    return DAYS_IN_MONTH[month - 1]


def _connect_fresh(path: Path) -> sqlite3.Connection:
    """Abre um banco vazio com layout fixo.

    `page_size` explícito e `journal_mode=off` existem para o arquivo ser
    reprodutível byte a byte: o `dataset.lock.json` guarda o SHA256, e um
    default que mude entre versões do SQLite invalidaria o lock de todos os
    lineages de uma vez.
    """
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA page_size = 4096")
    conn.execute("PRAGMA journal_mode = off")
    conn.executescript(SCHEMA)
    return conn


def _finish(conn: sqlite3.Connection) -> None:
    """Fecha o banco compactado — e sem estatísticas.

    `VACUUM` deixa o arquivo denso e determinístico. `ANALYZE` fica de fora de
    propósito: rodar `ANALYZE` é um dos movimentos que o candidato pode fazer em
    `setup.sql`, e entregá-lo pronto seria tirar um degrau da escada.
    """
    conn.commit()
    conn.execute("VACUUM")
    conn.commit()
    conn.close()


# ------------------------------------------------------------------ perf


def _build_perf(path: Path, n_customers: int, n_orders: int, seed: int) -> None:
    rnd = random.Random(seed)
    conn = _connect_fresh(path)

    customers = []
    for cid in range(1, n_customers + 1):
        # ~1% sem região: `region` sai NULL no result set e o contrato manda
        # devolvê-lo como está. Um candidato que "limpa" o NULL diverge.
        region = None if rnd.random() < 0.01 else rnd.choice(REGIONS)
        customers.append(
            (
                cid,
                f"Cliente {cid:05d}",
                region,
                rnd.choice(SEGMENTS),
                f"202{rnd.randrange(0, 3)}-{rnd.randrange(1, 13):02d}-{rnd.randrange(1, 29):02d}",
            )
        )
    conn.executemany("INSERT INTO customers VALUES (?,?,?,?,?)", customers)

    # 24 meses: a janela medida cobre 3 ou 12 deles, então o filtro de data
    # descarta a maior parte da tabela. Sem índice em `orders` isso é uma
    # varredura das páginas de dados inteiras — é essa a diferença que um índice
    # cobrindo captura.
    months = [(2023 + (m // 12), (m % 12) + 1) for m in range(24)]

    orders = []
    items = []
    refunds = []
    item_id = 0
    refund_id = 0
    for order_id in range(1, n_orders + 1):
        # Lei de potência nas compras: uma minoria de clientes concentra a
        # receita. Sem isso o ranking por mês seria um sorteio entre valores
        # quase iguais e a ordenação do result set não teria significado.
        idx = int(n_customers * (rnd.random() ** 2.4))
        customer_id = min(idx, n_customers - 1) + 1
        year, month = months[rnd.randrange(len(months))]
        day = rnd.randrange(1, _month_days(year, month) + 1)
        status = rnd.choice(STATUSES)
        orders.append(
            (
                order_id,
                customer_id,
                f"{year:04d}-{month:02d}-{day:02d}",
                status,
                rnd.choice(CHANNELS),
                rnd.choice(PAYMENTS),
                rnd.choice(CITIES),
                rnd.choice(UFS),
                f"{rnd.randrange(10_000, 99_999):05d}-{rnd.randrange(0, 999):03d}",
                f"CUPOM{rnd.randrange(9999):04d}" if rnd.random() < 0.25 else None,
                rnd.choice(DEVICES),
                # A nota é o grosso do peso da linha. Ela existe para que varrer
                # `orders` custe leitura de página de verdade, e não só CPU.
                f"pedido {order_id} via {rnd.choice(CHANNELS)} conferido em "
                f"{rnd.randrange(10**12):012d} lote {rnd.randrange(99_999):05d} "
                f"origem {rnd.choice(CITIES)} obs {rnd.randrange(10**14):014d}",
            )
        )
        for _ in range(rnd.randrange(1, 4)):
            item_id += 1
            items.append(
                (
                    item_id,
                    order_id,
                    rnd.randrange(1, 4000),
                    rnd.randrange(1, 7),
                    rnd.randrange(150, 90_000),
                )
            )
        if rnd.random() < 0.09:
            refund_id += 1
            refunds.append(
                (
                    refund_id,
                    order_id,
                    rnd.randrange(100, 120_000),
                    f"{year:04d}-{month:02d}-{day:02d}",
                )
            )

    conn.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", orders)
    conn.executemany("INSERT INTO order_items VALUES (?,?,?,?,?)", items)
    conn.executemany("INSERT INTO refunds VALUES (?,?,?,?)", refunds)
    _finish(conn)


# ------------------------------------------------------------------ gate


class _GateBuilder:
    """Monta o banco de gate linha a linha, com um motivo por linha.

    O objetivo não é parecer um banco de verdade — é que cada leitura errada do
    contrato produza um result set diferente. Cada `_order` abaixo existe para
    matar um mutante específico; quando um mutante sobrevive ao `--selftest`, é
    aqui que se planta a linha que o mata.
    """

    def __init__(self) -> None:
        self.customers: list[tuple] = []
        self.orders: list[tuple] = []
        self.items: list[tuple] = []
        self.refunds: list[tuple] = []
        self._order_id = 0
        self._item_id = 0
        self._refund_id = 0

    def customer(self, cid: int, region: str | None, segment: str = "varejo") -> None:
        self.customers.append((cid, f"Cliente {cid:05d}", region, segment, "2022-01-15"))

    def order(
        self,
        customer_id: int,
        date: str,
        item_values: list[tuple[int, int]],
        status: str = "delivered",
        refund: int | None = None,
    ) -> int:
        """Um pedido. `item_values` são pares (qty, unit_cents); `refund` em centavos."""
        self._order_id += 1
        oid = self._order_id
        self.orders.append(
            (oid, customer_id, date, status, "web", "pix", "Recife", "PE", "50000-000",
             None, "ios", f"pedido {oid}")
        )
        for qty, unit in item_values:
            self._item_id += 1
            self.items.append((self._item_id, oid, 100 + (self._item_id % 37), qty, unit))
        if refund is not None:
            self._refund_id += 1
            self.refunds.append((self._refund_id, oid, refund, date))
        return oid


def _gate_rows() -> _GateBuilder:
    g = _GateBuilder()

    for cid in range(1, 13):
        g.customer(cid, REGIONS[cid % len(REGIONS)])
    g.customer(13, None)  # região NULL: o contrato manda propagar o NULL
    g.customer(14, "Sul")  # nenhum pedido: não pode aparecer no result set

    # --- 2023-12: mês inteiro fora da janela [2024-01-01, ...) do primeiro
    # conjunto de parâmetros, e dentro da janela larga do terceiro. Pega filtro
    # de data frouxo na borda inferior.
    g.order(1, "2023-12-31", [(2, 50_000)])
    g.order(2, "2023-12-01", [(1, 9_900)], refund=9_900)

    # --- 2024-01: o mês do ranking, montado para separar RANK de ROW_NUMBER.
    # Clientes 1 e 2 empatam em líquido exatamente; o desempate do ORDER BY é
    # customer_id, mas o RANK dos dois é o mesmo número.
    g.order(1, "2024-01-01", [(1, 300_000)])  # borda inferior inclusiva
    g.order(2, "2024-01-05", [(3, 100_000)])
    # Cliente 3 fica logo abaixo, com estorno que derruba o líquido.
    g.order(3, "2024-01-09", [(2, 200_000)], refund=120_000)
    # Cliente 4: quatro itens no mesmo pedido MAIS estorno. Se o candidato juntar
    # `refunds` no nível do item, o estorno é contado quatro vezes.
    g.order(4, "2024-01-11", [(1, 20_000), (2, 15_000), (3, 5_000), (1, 40_000)], refund=30_000)
    # Cliente 5: pedido sem nenhum item. Conta em n_pedidos, soma zero em bruto.
    # Um INNER JOIN com order_items faz este pedido — e o cliente — sumirem.
    g.order(5, "2024-01-12", [])
    g.order(5, "2024-01-13", [(1, 70_000)])
    # Cliente 6: pedido sem item E com estorno. bruto = 0 e estorno > 0, então
    # pct_estorno cai na regra do denominador zero e o líquido fica negativo.
    g.order(6, "2024-01-14", [], refund=45_000)
    # Cliente 7: estorno exatamente igual ao bruto. Líquido zero, pct = 100.00.
    g.order(7, "2024-01-15", [(1, 80_000)], refund=80_000)
    # Cliente 8: bruto 30000 e estorno 10000 -> pct = 33.33. Exige arredondar.
    g.order(8, "2024-01-16", [(1, 30_000)], refund=10_000)
    # Cliente 9: dois pedidos cujo pct por pedido arredonda diferente do pct do
    # grupo. Arredondar por pedido e tirar média dá 33.34; o contrato dá 33.33.
    g.order(9, "2024-01-17", [(1, 30_000)], refund=10_000)
    g.order(9, "2024-01-18", [(1, 3)], refund=1)
    # Cliente 10: mesmo mês, quatro status. Só o `delivered` entra; os outros
    # três existem para pegar filtro de status errado, e o `returned` em
    # particular para pegar quem lê "não cancelado" no lugar de "entregue".
    g.order(10, "2024-01-19", [(1, 60_000)])
    g.order(10, "2024-01-20", [(1, 900_000)], status="pending")
    g.order(10, "2024-01-21", [(1, 900_000)], status="cancelled")
    g.order(10, "2024-01-22", [(1, 900_000)], status="returned", refund=900_000)
    # Cliente 11 e 12: caudinha do ranking, para o corte por top_n morder.
    g.order(11, "2024-01-23", [(1, 11_000)])
    g.order(12, "2024-01-24", [(1, 10_000)])
    g.order(13, "2024-01-25", [(1, 9_000)])  # região NULL no result set
    # Cliente 1 de novo: dois pedidos no mesmo mês, para n_pedidos != 1 e para o
    # empate acima só existir depois de somar o grupo inteiro.
    g.order(1, "2024-01-28", [(1, 1)])
    g.order(2, "2024-01-29", [(1, 1)])

    # --- 2024-02: mês com bissexto e com empate triplo na fronteira do top_n.
    g.order(1, "2024-02-01", [(1, 100_000)])
    g.order(2, "2024-02-29", [(1, 100_000)])  # 29 de fevereiro existe em 2024
    g.order(3, "2024-02-15", [(1, 100_000)])
    g.order(4, "2024-02-16", [(2, 25_000)], refund=1)
    g.order(5, "2024-02-17", [(1, 40_000)])
    # Estorno maior que a venda: líquido negativo, e o ranking tem que aceitar.
    g.order(6, "2024-02-18", [(1, 10_000)], refund=95_000)

    # --- 2024-03: mês com só dois clientes. Com top_n = 5 saem dois registros,
    # não cinco: quem materializa "sempre top_n linhas" quebra aqui.
    g.order(7, "2024-03-05", [(1, 12_345)])
    g.order(8, "2024-03-31", [(1, 12_000)])  # borda superior exclusiva do 1º set

    # --- 2024-04: existe só para a borda. Com d1 = '2024-04-01' nenhuma destas
    # linhas pode aparecer; um `<=` no lugar de `<` traz a primeira.
    g.order(9, "2024-04-01", [(1, 777_000)])
    g.order(10, "2024-04-02", [(1, 5_000)])

    return g


def _build_gate(path: Path) -> None:
    g = _gate_rows()
    conn = _connect_fresh(path)
    conn.executemany("INSERT INTO customers VALUES (?,?,?,?,?)", g.customers)
    conn.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", g.orders)
    conn.executemany("INSERT INTO order_items VALUES (?,?,?,?,?)", g.items)
    conn.executemany("INSERT INTO refunds VALUES (?,?,?,?)", g.refunds)
    _finish(conn)
    _assert_gate_has_teeth(path)


def _assert_gate_has_teeth(path: Path) -> None:
    """Prova que o banco de gate distingue os erros que ele deveria distinguir.

    Não é decoração: é a Falha 1 virada em código. Um banco de gate que não
    separa o certo do errado é pior que nenhum, porque dá sensação de proteção.
    As três propriedades abaixo são pré-condições dos mutantes de `eval.py` — se
    alguma sumir numa edição do gerador, o `--selftest` só reclamaria muito
    depois, e com uma mensagem que não aponta para cá.
    """
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        checks = [
            (
                "pedido entregue sem nenhum item",
                "SELECT COUNT(*) FROM orders o WHERE o.status = 'delivered' "
                "AND NOT EXISTS (SELECT 1 FROM order_items i WHERE i.order_id = o.order_id)",
            ),
            (
                "pedido com estorno e mais de um item (armadilha de fan-out)",
                "SELECT COUNT(*) FROM refunds r JOIN order_items i ON i.order_id = r.order_id "
                "GROUP BY r.order_id HAVING COUNT(*) > 1",
            ),
            (
                "pedido exatamente na borda inferior da janela",
                "SELECT COUNT(*) FROM orders WHERE order_date = '2024-01-01'",
            ),
            (
                "pedido exatamente na borda superior exclusiva",
                "SELECT COUNT(*) FROM orders WHERE order_date = '2024-04-01'",
            ),
            (
                "cliente sem nenhum pedido",
                "SELECT COUNT(*) FROM customers c WHERE NOT EXISTS "
                "(SELECT 1 FROM orders o WHERE o.customer_id = c.customer_id)",
            ),
            (
                "cliente com regiao NULL e pedido entregue",
                "SELECT COUNT(*) FROM customers c JOIN orders o USING (customer_id) "
                "WHERE c.region IS NULL AND o.status = 'delivered'",
            ),
            (
                "estorno maior que o bruto do pedido (liquido negativo)",
                "SELECT COUNT(*) FROM refunds r WHERE r.amount_cents > COALESCE("
                "(SELECT SUM(i.qty * i.unit_cents) FROM order_items i "
                "WHERE i.order_id = r.order_id), 0)",
            ),
        ]
        for label, sql in checks:
            row = conn.execute(sql).fetchone()
            if row is None or row[0] < 1:
                raise AssertionError(
                    f"gate_shop.sqlite não tem {label}: o gate ficaria cego para o mutante "
                    "correspondente. Plante a linha em `_gate_rows`."
                )

        # Empate exato de líquido dentro de um mês: é a única coisa que separa
        # RANK de ROW_NUMBER. Sem isso, os dois mutantes são indistinguíveis.
        empates = conn.execute(
            """
            WITH liq AS (
                SELECT substr(o.order_date, 1, 7) AS mes, o.customer_id,
                       SUM(COALESCE((SELECT SUM(i.qty * i.unit_cents) FROM order_items i
                                     WHERE i.order_id = o.order_id), 0))
                       - SUM(COALESCE((SELECT r.amount_cents FROM refunds r
                                       WHERE r.order_id = o.order_id), 0)) AS liquido
                FROM orders o WHERE o.status = 'delivered'
                GROUP BY 1, 2
            )
            SELECT mes, liquido, COUNT(*) FROM liq GROUP BY mes, liquido HAVING COUNT(*) > 1
            """
        ).fetchall()
        if not empates:
            raise AssertionError(
                "gate_shop.sqlite não tem empate exato de líquido em nenhum mês: RANK e "
                "ROW_NUMBER produziriam o mesmo result set e o mutante passaria."
            )
    finally:
        conn.close()


# ------------------------------------------------------------------ specs


def specs() -> list[datakit.DatasetSpec]:
    return [
        datakit.DatasetSpec(
            PERF_DB,
            lambda p: _build_perf(p, n_customers=5000, n_orders=200_000, seed=20240131),
            purpose="banco de performance: 24 meses, 200k pedidos largos, ~400k itens. So mede tempo.",
            rows=200_000,
        ),
        datakit.DatasetSpec(
            GATE_DB,
            _build_gate,
            purpose="UNICO banco que decide correcao: bordas de data, empates, fan-out, NULLs",
            rows=None,
        ),
    ]


def main() -> int:
    report = datakit.generate(HERE, specs(), force="--force" in sys.argv)
    print(f"sql_agg: {report.render()}")
    ok, detail = datakit.verify_lock(HERE)
    print(f"lock: {detail}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
