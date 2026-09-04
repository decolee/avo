"""f(x) do target sql_workload — o árbitro. Nunca afrouxe isto para um candidato passar.

O candidato aqui não é um artefato, são NOVE: oito consultas independentes mais o
esquema físico que elas compartilham.

  q1..q8.sql   os oito relatórios do fechamento. Cada um é UM `SELECT`/`WITH`,
               com os parâmetros nomeados que o seu contrato declara.
  setup.sql    DDL opcional executada ANTES do lote e cronometrada junto no
               regime frio. Índice, view e `ANALYZE` — nada que altere dados.

## Por que este alvo existe

`docs/TARGET_DESIGN.md` §3e: um alvo cujo espaço uma sessão esgota em cem
segundos não consegue comparar arquiteturas de busca, e os cinco alvos
anteriores têm esse defeito — a sonda de 100 s captura de 46% a 254% do headroom
declarado. O regime do paper (sete dias, centenas de iterações) só existe onde a
busca não termina em meia hora.

Duas propriedades deste alvo tentam produzir esse regime, e as duas foram
MEDIDAS, não presumidas (os números estão em `kb/20-medicao.md`):

1. **Amdahl de propósito.** Os oito relatórios custam a mesma ordem de grandeza
   no seed. Não existe primeiro movimento que capture o headroom: o maior deles
   vale 40% do ganho e os outros sete precisam ser feitos um a um.

2. **Os movimentos se destravam.** O melhor conjunto de índices vale **1,11x**
   aplicado às consultas do seed e **2,17x** aplicado às mesmas consultas
   reescritas. Índice sobre coluna que a consulta embrulha em função não é usado
   por ninguém — só custa tempo no regime frio. Quem cria índice primeiro mede
   quase nada e tem todo motivo para descartá-lo; o ganho só aparece para quem
   volta a testar depois de reescrever. Uma passada única não fecha esse ciclo.

## Separação entre gate e benchmark, e por quê

  CORREÇÃO    -> data/gate_loja.sqlite. Minúsculo, montado linha a linha, com
                 pedido entregue sem item, estorno maior que a venda, empate
                 exato de líquido, datas nas duas bordas da janela, cliente sem
                 pedido e estorno com data fora da janela. É o ÚNICO banco que
                 decide `correct`, e cada consulta é rodada nele com QUATRO
                 jogos de parâmetros — inclusive um que devolve zero linhas.
  PERFORMANCE -> data/perf_loja.sqlite. Grande, banal, congelado. Só mede tempo.

É a mesma separação do `etl_agg` e do `sql_agg`, pela mesma razão (Falha 1).

## Como a correção é decidida

Igualdade exata do result set, incluindo a ORDEM das linhas: o `ORDER BY` é
parte de cada contrato, e um relatório com as mesmas linhas em outra ordem é
outro relatório. Todo dinheiro é `INTEGER` em centavos, então `SUM` é exato e
independente da ordem em que o planejador visita as linhas — o gate pode exigir
igualdade sem reprovar uma otimização legítima pelo último bit da mantissa.

Antes do hash vêm as checagens que produzem mensagem útil: qual consulta, qual
janela, quantas colunas, quantas linhas, e a primeira célula divergente com o
esperado e o obtido lado a lado.

## Por que o banco de performance TAMBÉM é conferido

Separar o gate do benchmark abre um buraco que não existe quando os dois são o
mesmo dado: a consulta pode reconhecer em qual banco está e devolver o relatório
certo só no pequeno. `... AND (SELECT COUNT(*) FROM orders) < 1000` passa nas
quatro janelas do gate e devolve ZERO linha em cada regime cronometrado — tempo
de sobra, relatório nenhum. `checar_consistencia_perf` roda as oito consultas
nas janelas que o relógio cronometra, no banco grande, e exige o mesmo result
set da referência. É o análogo, para um alvo de SQL, do `implausible_speed` dos
alvos de Python. Ver os mutantes `trapaca_*`.
"""

from __future__ import annotations

import shutil
import sqlite3
import statistics
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from labkit import contracts, datakit, evalkit  # noqa: E402

SETUP_FILE = "setup.sql"
ENTRYPOINT = SETUP_FILE

PERF_DB = "perf_loja.sqlite"
GATE_DB = "gate_loja.sqlite"

#: Toda cópia que o candidato chega a enxergar — a do gate, a da conferência no
#: banco medido e as do relógio — é criada com ESTE prefixo de diretório e ESTE
#: nome de arquivo. Não é cosmético: é o que impede que uma consulta descubra
#: pelo caminho se está sendo julgada, conferida ou cronometrada. Com nomes
#: iguais, o único sinal que distingue os bancos é o CONTEÚDO — e usar o
#: conteúdo para mudar a resposta é o que `checar_consistencia_perf` reprova.
PREFIXO_COPIA = "sql_workload_copia_"
NOME_COPIA = "copia.sqlite"

#: Teto de tempo de parede para UMA execução de SQL. Não é orçamento de score: é
#: o freio que impede um candidato com produto cartesiano de segurar o harness
#: por dez minutos. Generoso o bastante para que nenhuma consulta honesta chegue
#: perto — a mais lenta do seed leva 0,3 s.
LIMITE_SQL_S = 45.0

#: As oito consultas do fechamento, e quais parâmetros nomeados cada uma recebe.
#: A lista é do AVALIADOR, não do candidato: apagar um arquivo, esvaziar uma
#: consulta ou responder com menos colunas reprova. `escopo` é o nome da janela
#: que cada relatório usa dentro de um regime — a razão de eles diferirem está em
#: `kb/00-contrato.md`: um fechamento real não roda todos os relatórios no mesmo
#: período, e é isso que mantém os oito custando a mesma ordem de grandeza no
#: seed (sem isso, um deles sozinho valeria 75% do headroom — foi medido).
CONSULTAS = (
    ("q1_receita_mensal", ("d0", "d1"), "trimestre"),
    ("q2_top_produtos", ("d0", "d1", "top_n"), "trimestre"),
    ("q3_ranking_regiao", ("d0", "d1", "top_n"), "trimestre"),
    ("q4_clientes_inativos", ("d0", "d1"), "trimestre"),
    ("q5_canal_ou_pais", ("d0", "d1", "canal", "pais"), "trimestre"),
    ("q6_cesta_por_segmento", ("d0", "d1"), "semana"),
    ("q7_primeira_compra", ("d0", "d1"), "mes"),
    ("q8_conciliacao_diaria", ("d0", "d1"), "trimestre"),
)

NOMES = tuple(nome for nome, _, _ in CONSULTAS)
ARQUIVOS = tuple(f"{nome}.sql" for nome in NOMES)

#: O lote trimestral: o fechamento que os regimes `frio` e `quente` cronometram.
JANELAS_LOTE = {
    "trimestre": ("2024-01-01", "2024-04-01"),
    "mes": ("2024-02-01", "2024-03-01"),
    "semana": ("2024-02-05", "2024-02-12"),
}
EXTRAS_LOTE = {
    "q2_top_produtos": {"top_n": 25},
    "q3_ranking_regiao": {"top_n": 10},
    "q5_canal_ou_pais": {"canal": "app", "pais": "AR"},
}

#: O lote quinzenal, com parâmetros raros. Não é "o mesmo benchmark de novo":
#: é uma SELETIVIDADE diferente. No trimestre, 12% da tabela casa o predicado e
#: um índice mal escolhido perde para a varredura; na quinzena com canal e país
#: raros, menos de 1% casa e o índice decide tudo. Uma mudança que ajuda um
#: regime e regride o outro perde para uma que melhora os dois — e essa é a
#: tensão que impede que a resposta seja "crie todos os índices".
JANELAS_ESTREITO = {
    "trimestre": ("2024-05-06", "2024-05-20"),
    "mes": ("2024-05-06", "2024-05-20"),
    "semana": ("2024-05-06", "2024-05-09"),
}
EXTRAS_ESTREITO = {
    "q2_top_produtos": {"top_n": 5},
    "q3_ranking_regiao": {"top_n": 3},
    "q5_canal_ou_pais": {"canal": "parceiro", "pais": "PY"},
}


def _lote(janelas: dict, extras: dict) -> dict[str, dict]:
    saida = {}
    for nome, usados, escopo in CONSULTAS:
        d0, d1 = janelas[escopo]
        params = {"d0": d0, "d1": d1, **extras.get(nome, {})}
        saida[nome] = {k: params[k] for k in usados}
    return saida


LOTE = _lote(JANELAS_LOTE, EXTRAS_LOTE)
LOTE_ESTREITO = _lote(JANELAS_ESTREITO, EXTRAS_ESTREITO)

#: Os jogos de parâmetros do gate, aplicados a TODAS as oito consultas. O
#: terceiro cobre as duas bordas da janela de propósito; o quarto devolve zero
#: linha na maioria dos relatórios — um result set vazio ainda tem que ter o
#: número certo de colunas, e candidato que estoura em janela vazia é candidato
#: errado. Rodar com vários jogos é o que separa "a consulta está certa" de "a
#: consulta acerta esta janela".
PARAMS_GATE = (
    {"d0": "2024-01-01", "d1": "2024-04-01", "top_n": 2, "canal": "app", "pais": "AR"},
    {"d0": "2024-02-01", "d1": "2024-03-01", "top_n": 3, "canal": "web", "pais": "BR"},
    {"d0": "2023-12-01", "d1": "2024-05-01", "top_n": 50, "canal": "loja", "pais": "PY"},
    {"d0": "2024-04-02", "d1": "2024-04-03", "top_n": 5, "canal": "web", "pais": "BR"},
)


def data(name: str) -> Path:
    return datakit.data_dir(HERE) / name


# ----------------------------------------------------- leitura e execução de SQL


def _sem_comentarios(sql: str) -> str:
    """Remove comentários e o conteúdo de literais de texto.

    As checagens estáticas rodam sobre isto, não sobre o SQL cru: senão um
    comentário `-- não use DELETE` reprovaria um candidato honesto, e um `DROP`
    escondido dentro de um comentário passaria a impressão de ter sido
    inspecionado quando não foi.
    """
    out = []
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        if c == "-" and sql.startswith("--", i):
            i = sql.find("\n", i)
            if i < 0:
                break
            continue
        if c == "/" and sql.startswith("/*", i):
            fim = sql.find("*/", i + 2)
            i = n if fim < 0 else fim + 2
            out.append(" ")
            continue
        if c == "'":
            j = i + 1
            while j < n:
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            out.append("''")
            i = j + 1
            continue
        if c in '"`':
            fim = sql.find(c, i + 1)
            out.append(sql[i : (n if fim < 0 else fim + 1)])
            i = n if fim < 0 else fim + 1
            continue
        if c == "[":
            fim = sql.find("]", i + 1)
            out.append(sql[i : (n if fim < 0 else fim + 1)])
            i = n if fim < 0 else fim + 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def statements(sql: str) -> list[str]:
    """Quebra o script em comandos, ignorando `;` dentro de texto e comentário."""
    partes = [p.strip() for p in _sem_comentarios(sql).split(";")]
    return [p for p in partes if p]


def _palavras(texto: str) -> set[str]:
    import re

    return set(re.findall(r"[a-z_]+", texto.lower()))


#: Palavras que não podem aparecer numa consulta. A conexão de leitura já
#: recusaria a escrita, mas uma mensagem que nomeia a palavra encontrada vale um
#: passo inteiro do agente contra um `attempt to write a readonly database`.
PROIBIDO_NA_CONSULTA = (
    "create",
    "drop",
    "insert",
    "update",
    "delete",
    "alter",
    "attach",
    "detach",
    "pragma",
    "vacuum",
    "reindex",
)

#: `PRAGMA` é um comando e cai na lista acima, mas as funções de tabela
#: `pragma_*` (`SELECT file FROM pragma_database_list`) são um SELECT comum e
#: passariam batido — a checagem de palavra vê o token inteiro
#: `pragma_database_list`, que não é igual a `pragma`. Elas não leem dado nenhum:
#: leem o AMBIENTE. Com o caminho do arquivo em mãos, a consulta descobre se está
#: sendo julgada ou cronometrada e pode acertar o relatório só onde é julgada.
PREFIXO_PRAGMA = "pragma"


def _funcoes_de_ambiente(texto: str) -> set[str]:
    return {p for p in _palavras(texto) if p.startswith(PREFIXO_PRAGMA)} - {PREFIXO_PRAGMA}


def _recusa_ambiente(arquivo: str, achadas: set[str]) -> str:
    return (
        f"{arquivo} usa {', '.join(sorted(achadas)).upper()}: as funções de tabela `pragma_*` "
        "não leem os dados, leem o ambiente — `pragma_database_list` devolve o caminho do "
        "arquivo aberto. Uma consulta que enxerga em QUAL banco está pode acertar o relatório "
        "só onde é julgada e devolver nada onde é cronometrada. O alvo mede a consulta, não o "
        "reconhecimento do arquivo."
    )


def checar_consulta(arquivo: str, sql: str) -> tuple[bool, str]:
    """Cada consulta tem que ser UM `SELECT`/`WITH` e nada além disso."""
    cmds = statements(sql)
    if not cmds:
        return False, f"{arquivo} está vazio: era esperado um SELECT"
    if len(cmds) > 1:
        return False, (
            f"{arquivo} tem {len(cmds)} comandos; é permitido exatamente um. "
            "DDL vai em setup.sql, e só índice, view ou ANALYZE."
        )
    primeira = cmds[0].split()[0].lower() if cmds[0].split() else ""
    if primeira not in ("select", "with"):
        return False, (
            f"{arquivo} começa com {primeira.upper()!r}; a consulta avaliada tem que ser um "
            "SELECT (podendo abrir com WITH)."
        )
    ambiente = _funcoes_de_ambiente(cmds[0])
    if ambiente:
        return False, _recusa_ambiente(arquivo, ambiente)
    achadas = _palavras(cmds[0]) & set(PROIBIDO_NA_CONSULTA)
    if achadas:
        return False, (
            f"{arquivo} contém {', '.join(sorted(achadas)).upper()}: a consulta medida só pode "
            "ler. Índice e view vão em setup.sql."
        )
    return True, "ok"


def checar_setup(sql: str) -> tuple[bool, str]:
    """`setup.sql` só pode preparar o banco, nunca mudar o que ele responde."""
    permitidos = ("analyze", "create index ", "create unique index ", "create view ")
    for cmd in statements(sql):
        low = " ".join(cmd.lower().split())
        # Antes do allowlist: uma `CREATE VIEW v AS SELECT file FROM
        # pragma_database_list` é um CREATE VIEW legítimo pelo prefixo e entrega
        # às consultas exatamente o que elas não podem ver.
        ambiente = _funcoes_de_ambiente(low)
        if ambiente:
            return False, _recusa_ambiente(SETUP_FILE, ambiente)
        if low.startswith(permitidos):
            continue
        if low.startswith("create table") or low.startswith("create virtual table"):
            return False, (
                f"{SETUP_FILE}: CREATE TABLE não é aceito. Guardar um relatório numa tabela faz "
                "o score subir sem que nenhuma consulta tenha ficado melhor — o alvo mede as "
                "consultas, não a memorização delas."
            )
        if low.startswith(("create temp ", "create temporary ")):
            return False, (
                f"{SETUP_FILE}: objeto temporário morre junto com a conexão de setup e não "
                "existiria na hora das consultas. Crie um índice permanente."
            )
        if low.startswith("pragma"):
            return False, (
                f"{SETUP_FILE}: PRAGMA vale só para a conexão que o executou, e as consultas "
                "rodam em outra. Não teria efeito nenhum na medição."
            )
        cabeca = " ".join(cmd.split()[:3])
        return False, (
            f"{SETUP_FILE}: {cabeca!r} não é permitido. Só CREATE INDEX, CREATE VIEW e ANALYZE — "
            "nada que altere dados."
        )
    return True, "ok"


def _freio(conn: sqlite3.Connection, limite_s: float = LIMITE_SQL_S) -> None:
    fim = time.perf_counter() + limite_s
    conn.set_progress_handler(lambda: 1 if time.perf_counter() > fim else 0, 20_000)


def rodar_setup(db: Path, sql: str) -> None:
    if not sql.strip():
        return
    conn = sqlite3.connect(db)
    try:
        _freio(conn)
        conn.executescript(sql)
        conn.commit()
    finally:
        conn.close()


def rodar_consulta(db: Path, sql: str, params: dict) -> tuple[int, list[tuple]]:
    """Executa uma consulta numa conexão SOMENTE LEITURA e devolve (n_colunas, linhas)."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        _freio(conn)
        cur = conn.execute(sql, params)
        linhas = cur.fetchall()
        n_cols = len(cur.description or ())
    finally:
        conn.close()
    return n_cols, linhas


def params_para(nome: str, jogo: dict) -> dict:
    """Recorta de um jogo de parâmetros só o que a consulta `nome` declara usar."""
    usados = next(u for n, u, _ in CONSULTAS if n == nome)
    return {k: jogo[k] for k in usados}


# ----------------------------------------------------------------- referência

#: As oito consultas corretas, escritas à mão. Elas definem o result set que o
#: gate exige e são o que `--baselines` mede como "o que um engenheiro escreveria
#: sem mexer no esquema" — a baseline real que o paper pede (§4 do
#: TARGET_DESIGN.md), e não apenas "mais rápido que o seed".
#:
#: Elas NÃO aparecem na KB. Achar a forma de cada consulta é o problema.
REFERENCIA: dict[str, str] = {
    "q1_receita_mensal": """
WITH bruto AS (
    SELECT o.order_id AS order_id, o.customer_id AS customer_id,
           substr(o.order_date, 1, 7) AS mes,
           COALESCE(SUM(i.qty * i.unit_cents), 0) AS bruto
    FROM orders o
    LEFT JOIN order_items i ON i.order_id = o.order_id
    WHERE o.status = 'delivered' AND o.order_date >= :d0 AND o.order_date < :d1
    GROUP BY o.order_id
)
SELECT b.mes AS mes, b.customer_id AS customer_id, COUNT(*) AS n_pedidos,
       SUM(b.bruto) AS bruto_cents,
       SUM(COALESCE(r.amount_cents, 0)) AS estorno_cents,
       SUM(b.bruto) - SUM(COALESCE(r.amount_cents, 0)) AS liquido_cents
FROM bruto b LEFT JOIN refunds r ON r.order_id = b.order_id
GROUP BY b.mes, b.customer_id
ORDER BY b.mes, liquido_cents DESC, b.customer_id
""",
    "q2_top_produtos": """
WITH ped AS (
    SELECT o.order_id AS order_id FROM orders o
    WHERE o.status = 'delivered' AND o.order_date >= :d0 AND o.order_date < :d1
)
SELECT i.sku AS sku, p.category AS category,
       SUM(i.qty) AS qty_total, SUM(i.qty * i.unit_cents) AS receita_cents,
       COUNT(DISTINCT i.order_id) AS n_pedidos
FROM ped d JOIN order_items i ON i.order_id = d.order_id
           JOIN products p ON p.sku = i.sku
GROUP BY i.sku, p.category
ORDER BY receita_cents DESC, sku
LIMIT :top_n
""",
    "q3_ranking_regiao": """
WITH ped AS (
    SELECT o.order_id AS order_id, o.customer_id AS customer_id FROM orders o
    WHERE o.status = 'delivered' AND o.order_date >= :d0 AND o.order_date < :d1
),
bruto AS (
    SELECT p.order_id AS order_id, p.customer_id AS customer_id,
           COALESCE(SUM(i.qty * i.unit_cents), 0) AS bruto
    FROM ped p LEFT JOIN order_items i ON i.order_id = p.order_id
    GROUP BY p.order_id
),
liq AS (
    SELECT COALESCE(c.region, 'sem_regiao') AS regiao, b.customer_id AS customer_id,
           SUM(b.bruto) - SUM(COALESCE(r.amount_cents, 0)) AS liquido_cents
    FROM bruto b JOIN customers c ON c.customer_id = b.customer_id
    LEFT JOIN refunds r ON r.order_id = b.order_id
    GROUP BY regiao, b.customer_id
),
rk AS (
    SELECT l.regiao AS regiao, l.customer_id AS customer_id, l.liquido_cents AS liquido_cents,
           RANK() OVER (PARTITION BY l.regiao ORDER BY l.liquido_cents DESC) AS rank_regiao
    FROM liq l
)
SELECT regiao, customer_id, liquido_cents, rank_regiao FROM rk
WHERE rank_regiao <= :top_n
ORDER BY regiao, rank_regiao, customer_id
""",
    "q4_clientes_inativos": """
SELECT c.customer_id AS customer_id, c.segment AS segment,
       COALESCE(c.region, 'sem_regiao') AS regiao, c.signup_date AS signup_date
FROM customers c
LEFT JOIN (SELECT DISTINCT o.customer_id AS customer_id FROM orders o
           WHERE o.status = 'delivered' AND o.order_date >= :d0 AND o.order_date < :d1) p
       ON p.customer_id = c.customer_id
WHERE c.signup_date < :d1 AND p.customer_id IS NULL
ORDER BY c.customer_id
""",
    "q5_canal_ou_pais": """
SELECT o.order_id AS order_id, o.customer_id AS customer_id, o.channel AS channel,
       o.ship_country AS ship_country, o.freight_cents AS freight_cents
FROM orders o
WHERE o.status = 'delivered' AND o.order_date >= :d0 AND o.order_date < :d1 AND o.channel = :canal
UNION
SELECT o.order_id, o.customer_id, o.channel, o.ship_country, o.freight_cents
FROM orders o
WHERE o.status = 'delivered' AND o.order_date >= :d0 AND o.order_date < :d1 AND o.ship_country = :pais
ORDER BY 1
""",
    "q6_cesta_por_segmento": """
WITH ped AS (
    SELECT o.order_id AS order_id, c.segment AS segment
    FROM orders o JOIN customers c ON c.customer_id = o.customer_id
    WHERE o.status = 'delivered' AND o.order_date >= :d0 AND o.order_date < :d1
)
SELECT p.segment AS segment, COUNT(DISTINCT p.order_id) AS n_pedidos,
       COALESCE(SUM(i.qty), 0) AS n_itens,
       COALESCE(SUM(i.qty * i.unit_cents), 0) AS bruto_cents,
       ROUND(1.0 * COALESCE(SUM(i.qty), 0) / COUNT(DISTINCT p.order_id), 3) AS itens_por_pedido
FROM ped p LEFT JOIN order_items i ON i.order_id = p.order_id
GROUP BY p.segment
ORDER BY p.segment
""",
    "q7_primeira_compra": """
WITH ped AS (
    SELECT o.order_id AS order_id, o.customer_id AS customer_id, o.order_date AS order_date,
           ROW_NUMBER() OVER (PARTITION BY o.customer_id ORDER BY o.order_date, o.order_id) AS rn
    FROM orders o
    WHERE o.status = 'delivered' AND o.order_date >= :d0 AND o.order_date < :d1
)
SELECT p.customer_id AS customer_id, p.order_id AS order_id, p.order_date AS order_date,
       COALESCE((SELECT SUM(i.qty * i.unit_cents) FROM order_items i
                 WHERE i.order_id = p.order_id), 0) AS bruto_cents
FROM ped p WHERE p.rn = 1 ORDER BY p.customer_id
""",
    "q8_conciliacao_diaria": """
WITH val AS (
    SELECT o.order_date AS dia,
           CASE WHEN o.status = 'delivered'
                THEN COALESCE((SELECT SUM(i.qty * i.unit_cents) FROM order_items i
                               WHERE i.order_id = o.order_id), 0) ELSE 0 END AS bruto,
           CASE WHEN o.status = 'delivered'
                THEN COALESCE((SELECT r.amount_cents FROM refunds r
                               WHERE r.order_id = o.order_id), 0) ELSE 0 END AS estorno
    FROM orders o WHERE o.order_date >= :d0 AND o.order_date < :d1
),
diario AS (
    SELECT dia, SUM(bruto) AS bruto_cents, SUM(estorno) AS estorno_cents
    FROM val GROUP BY dia
)
SELECT dia AS dia, bruto_cents AS bruto_cents, estorno_cents AS estorno_cents,
       bruto_cents - estorno_cents AS liquido_cents,
       SUM(bruto_cents - estorno_cents) OVER (ORDER BY dia ROWS UNBOUNDED PRECEDING) AS acumulado_cents
FROM diario ORDER BY dia
""",
}

#: O melhor `setup.sql` que este laboratório encontrou à mão. Serve só para
#: estimar em `--budget` a execução mais rápida imaginável — o piso de ruído tem
#: que ficar abaixo dela. Não aparece nas baselines nem na KB: achar a forma dos
#: índices, e principalmente descobrir que `ANALYZE` sozinho decide se o índice
#: ajuda ou atrapalha, é parte do problema.
SETUP_RAPIDO = "CREATE INDEX ix_ord_sd ON orders(status, order_date, customer_id);\nANALYZE;"


def plano(setup: str, trocas: dict[str, str] | None = None):
    """Empacota um candidato (setup + as oito consultas) como um chamável.

    `trocas` substitui consultas específicas da referência. É assim que cada
    mutante quebra UM relatório e deixa os outros sete corretos: se o gate
    aceitasse o plano, ele estaria cego para aquela leitura errada.
    """
    consultas = dict(REFERENCIA)
    consultas.update(trocas or {})

    def _plano() -> tuple[str, dict[str, str]]:
        return setup, consultas

    return _plano


def _troca(original: str, alvo: str, novo: str) -> str:
    """`str.replace` que grita quando o alvo sumiu.

    Os mutantes são derivados da referência por substituição. Se uma edição da
    referência apagar o trecho que um mutante altera, o mutante viraria uma cópia
    da referência — passaria no gate e o `--selftest` acusaria "gate furado" sem
    dizer que o problema é o mutante, não o gate.
    """
    if alvo not in original:
        raise AssertionError(f"trecho ausente na referência: {alvo[:70]!r}")
    return original.replace(alvo, novo, 1)


_ESPERADO: dict[tuple[str, str], tuple[int, list[tuple]]] = {}


def esperado(nome: str, params: dict) -> tuple[int, list[tuple]]:
    chave = (nome, repr(sorted(params.items())))
    if chave not in _ESPERADO:
        _ESPERADO[chave] = rodar_consulta(data(GATE_DB), REFERENCIA[nome], params)
    return _ESPERADO[chave]


# ----------------------------------------------------------------------- gate


def _celula(valor) -> str:
    """A mesma normalização que `canon_hash_rows` aplica.

    Existe só para a mensagem de erro: quem decide é o hash, mas "hash
    divergente" não diz ao agente o que consertar.
    """
    if isinstance(valor, float):
        return f"{valor:.6f}"
    return str(valor)


def comparar(nome: str, params: dict, n_cols: int, linhas: list[tuple]) -> tuple[bool, str]:
    esp_cols, esp_linhas = esperado(nome, params)
    janela = f"[{params['d0']}, {params['d1']})"
    extras = " ".join(f"{k}={v!r}" for k, v in sorted(params.items()) if k not in ("d0", "d1"))
    onde = f"{nome} janela {janela}{(' ' + extras) if extras else ''}"

    if n_cols != esp_cols:
        return False, (
            f"{onde}: {n_cols} colunas, esperadas {esp_cols}. A ordem e o conjunto de colunas "
            "fazem parte do contrato (kb/00-contrato.md)."
        )
    if len(linhas) != len(esp_linhas):
        return False, (
            f"{onde}: {len(linhas)} linhas, esperadas {len(esp_linhas)}. Linha a mais costuma "
            "ser filtro frouxo de data ou de status, ou fan-out de junção; linha a menos, "
            "LEFT JOIN virado em INNER."
        )
    if contracts.canon_hash_rows(linhas) == contracts.canon_hash_rows(esp_linhas):
        return True, "ok"

    for i, (obtida, esp) in enumerate(zip(linhas, esp_linhas, strict=True)):
        if [_celula(v) for v in obtida] != [_celula(v) for v in esp]:
            for j, (a, b) in enumerate(zip(obtida, esp, strict=True)):
                if _celula(a) != _celula(b):
                    return False, (
                        f"{onde}: linha {i} coluna {j} divergente — esperado {b!r}, obtido "
                        f"{a!r}. Linha esperada: {esp!r}"
                    )
            return False, f"{onde}: linha {i} divergente — esperada {esp!r}"
    return False, f"{onde}: hash divergente sem célula divergente (tipos?)"


def judge(candidato) -> tuple[bool, str]:
    """Roda as oito consultas no banco adversarial, nas quatro janelas, e decide."""
    setup_sql, consultas = candidato()

    ok, detalhe = checar_setup(setup_sql)
    if not ok:
        return False, detalhe
    for nome in NOMES:
        if nome not in consultas or not consultas[nome].strip():
            return False, (
                f"{nome}.sql ausente ou vazio. As oito consultas do fechamento são exigidas: "
                "apagar um relatório não é otimizar o fechamento."
            )
        ok, detalhe = checar_consulta(f"{nome}.sql", consultas[nome])
        if not ok:
            return False, detalhe

    with tempfile.TemporaryDirectory(prefix=PREFIXO_COPIA) as tmp:
        db = Path(tmp) / NOME_COPIA
        shutil.copyfile(data(GATE_DB), db)
        try:
            rodar_setup(db, setup_sql)
        except sqlite3.Error as exc:
            return False, f"{SETUP_FILE} falhou: {type(exc).__name__}: {exc}"
        for jogo in PARAMS_GATE:
            for nome in NOMES:
                params = params_para(nome, jogo)
                try:
                    n_cols, linhas = rodar_consulta(db, consultas[nome], params)
                except sqlite3.Error as exc:
                    return False, (
                        f"{nome} janela [{params['d0']}, {params['d1']}): "
                        f"{type(exc).__name__}: {exc}"
                    )
                ok, detalhe = comparar(nome, params, n_cols, linhas)
                if not ok:
                    return False, detalhe
    return True, "ok"


GATE = evalkit.Gate(
    judge=judge, description="banco adversarial, oito relatórios, quatro janelas, ordem exata"
)


# ------------------------------------------------------------------- mutantes
#
# Cada mutante quebra UM dos oito relatórios e deixa os outros sete corretos. Não
# são bugs absurdos: são as leituras erradas que um otimizador de verdade
# produziria ao reescrever aquela consulta — trocar `LEFT JOIN` por `JOIN` ao
# achatar uma subconsulta, contar linhas em vez de pedidos ao remover um
# `DISTINCT`, atribuir o estorno pela data dele em vez da data do pedido. Cada um
# depende de uma linha PLANTADA em `make_data.py`, e o gerador se recusa a
# escrever um banco de gate sem ela.

Q1, Q2, Q3 = (
    REFERENCIA["q1_receita_mensal"],
    REFERENCIA["q2_top_produtos"],
    REFERENCIA["q3_ranking_regiao"],
)
Q4, Q5 = REFERENCIA["q4_clientes_inativos"], REFERENCIA["q5_canal_ou_pais"]
Q6, Q7, Q8 = (
    REFERENCIA["q6_cesta_por_segmento"],
    REFERENCIA["q7_primeira_compra"],
    REFERENCIA["q8_conciliacao_diaria"],
)

MUTANTES = [
    # --- q1: a janela, o status e a atribuição do estorno
    (
        "q1_status_nao_cancelado",
        {"q1_receita_mensal": _troca(Q1, "o.status = 'delivered'", "o.status <> 'cancelled'")},
    ),
    (
        "q1_data_final_inclusiva",
        {"q1_receita_mensal": _troca(Q1, "o.order_date < :d1", "o.order_date <= :d1")},
    ),
    (
        "q1_itens_com_inner_join",
        {"q1_receita_mensal": _troca(Q1, "LEFT JOIN order_items i", "JOIN order_items i")},
    ),
    # O estorno pertence ao dia do PEDIDO. Filtrá-lo pela própria data parece
    # zelo com a janela e muda o número: o banco de gate tem um estorno cuja
    # `refund_date` cai fora da janela do pedido que o originou.
    (
        "q1_estorno_pela_data_do_estorno",
        {
            "q1_receita_mensal": _troca(
                Q1,
                "LEFT JOIN refunds r ON r.order_id = b.order_id",
                "LEFT JOIN refunds r ON r.order_id = b.order_id "
                "AND r.refund_date >= :d0 AND r.refund_date < :d1",
            )
        },
    ),
    (
        "q1_sem_order_by",
        {"q1_receita_mensal": _troca(Q1, "ORDER BY b.mes, liquido_cents DESC, b.customer_id", "")},
    ),
    # --- q2: pedidos versus linhas de item, e o corte
    (
        "q2_conta_linhas_e_nao_pedidos",
        {"q2_top_produtos": _troca(Q2, "COUNT(DISTINCT i.order_id)", "COUNT(*)")},
    ),
    ("q2_sem_corte_top_n", {"q2_top_produtos": _troca(Q2, "LIMIT :top_n", "")}),
    (
        "q2_ordena_por_quantidade",
        {
            "q2_top_produtos": _troca(
                Q2, "ORDER BY receita_cents DESC, sku", "ORDER BY qty_total DESC, sku"
            )
        },
    ),
    # --- q3: posto, região nula e estorno
    (
        "q3_row_number_no_lugar_de_rank",
        {"q3_ranking_regiao": _troca(Q3, "RANK() OVER", "ROW_NUMBER() OVER")},
    ),
    (
        "q3_regiao_nula_sem_coalesce",
        {
            "q3_ranking_regiao": _troca(
                Q3, "COALESCE(c.region, 'sem_regiao') AS regiao", "c.region AS regiao"
            )
        },
    ),
    (
        "q3_estorno_com_inner_join",
        {"q3_ranking_regiao": _troca(Q3, "LEFT JOIN refunds r", "JOIN refunds r")},
    ),
    # --- q4: quem entra na base de reativação
    (
        "q4_esquece_o_signup",
        {
            "q4_clientes_inativos": _troca(
                Q4,
                "WHERE c.signup_date < :d1 AND p.customer_id IS NULL",
                "WHERE p.customer_id IS NULL",
            )
        },
    ),
    (
        "q4_qualquer_status_conta",
        {
            "q4_clientes_inativos": _troca(
                Q4,
                "WHERE o.status = 'delivered' AND o.order_date >= :d0",
                "WHERE o.order_date >= :d0",
            )
        },
    ),
    # --- q5: o pedido que casa os DOIS critérios
    ("q5_union_all_duplica", {"q5_canal_ou_pais": _troca(Q5, "\nUNION\n", "\nUNION ALL\n")}),
    # --- q6: pedido versus linha de item
    (
        "q6_conta_linhas_e_nao_pedidos",
        {
            "q6_cesta_por_segmento": _troca(
                Q6, "COUNT(DISTINCT p.order_id) AS n_pedidos", "COUNT(*) AS n_pedidos"
            )
        },
    ),
    (
        "q6_itens_com_inner_join",
        {"q6_cesta_por_segmento": _troca(Q6, "LEFT JOIN order_items i", "JOIN order_items i")},
    ),
    # --- q7: qual pedido é o "primeiro"
    (
        "q7_pega_a_ultima_compra",
        {
            "q7_primeira_compra": _troca(
                Q7,
                "ORDER BY o.order_date, o.order_id",
                "ORDER BY o.order_date DESC, o.order_id DESC",
            )
        },
    ),
    # `RANK` sem o desempate por `order_id` devolve as DUAS linhas do cliente que
    # tem dois pedidos entregues na mesma data. Trocar só a função não bastaria:
    # com `(order_date, order_id)` no ORDER BY nunca há empate, e `RANK` e
    # `ROW_NUMBER` dão o mesmo resultado -- o mutante seria uma cópia da
    # referência. O par (função, critério de ordem) é que decide.
    (
        "q7_rank_sem_desempate",
        {
            "q7_primeira_compra": _troca(
                Q7,
                "ROW_NUMBER() OVER (PARTITION BY o.customer_id ORDER BY o.order_date, o.order_id)",
                "RANK() OVER (PARTITION BY o.customer_id ORDER BY o.order_date)",
            )
        },
    ),
    # --- q8: o dia sem venda e o acumulado
    (
        "q8_dia_sem_venda_some",
        {
            "q8_conciliacao_diaria": _troca(
                Q8,
                "FROM orders o WHERE o.order_date >= :d0",
                "FROM orders o WHERE o.status = 'delivered' AND o.order_date >= :d0",
            )
        },
    ),
    (
        "q8_acumulado_vira_total",
        {
            "q8_conciliacao_diaria": _troca(
                Q8, "OVER (ORDER BY dia ROWS UNBOUNDED PRECEDING)", "OVER ()"
            )
        },
    ),
]

#: Os dois abaixo não erram conta nenhuma: erram as regras. Materializar o
#: relatório é a forma que reward hacking assume neste alvo, e o gate tem a
#: obrigação de não premiá-la.
SETUP_MATERIALIZA = (
    "CREATE TABLE resposta AS SELECT 1 AS a, 1 AS b, 1 AS c, 1 AS d, 1 AS e, 1 AS f;"
)
QUERY_COM_DDL = "CREATE INDEX ix_hack ON orders(order_date);\n" + Q1


MUTANTS = evalkit.MutantSuite(
    reference=plano(""),
    mutants=(
        [(nome, plano("", trocas)) for nome, trocas in MUTANTES]
        + [
            (
                "setup_materializa_resposta",
                plano(SETUP_MATERIALIZA, {"q1_receita_mensal": "SELECT * FROM resposta"}),
            ),
            ("ddl_dentro_da_consulta", plano("", {"q1_receita_mensal": QUERY_COM_DDL})),
        ]
    ),
)


# ------------------------------------- o relatório cronometrado é o relatório?

#: Os dois lotes que o relógio de fato executa. É sobre ESTES que a consistência
#: no banco de performance é exigida — conferir outra janela seria conferir o que
#: ninguém mediu.
LOTES_MEDIDOS = (("lote", LOTE), ("estreito", LOTE_ESTREITO))

_ESPERADO_PERF: dict[tuple[str, str], tuple[int, int, str]] = {}


def esperado_perf(nome: str, params: dict) -> tuple[int, int, str]:
    """`(n_colunas, n_linhas, hash)` da referência no banco de performance.

    Calculado uma vez por processo, direto no arquivo congelado — a conexão é
    somente leitura e quem roda aqui é a REFERÊNCIA, que não tem interesse em
    descobrir onde está. É pago fora de qualquer relógio.
    """
    chave = (nome, repr(sorted(params.items())))
    if chave not in _ESPERADO_PERF:
        n_cols, linhas = rodar_consulta(data(PERF_DB), REFERENCIA[nome], params)
        _ESPERADO_PERF[chave] = (n_cols, len(linhas), contracts.canon_hash_rows(linhas))
    return _ESPERADO_PERF[chave]


def checar_consistencia_perf(setup_sql: str, consultas: dict[str, str]) -> tuple[bool, str]:
    """As oito consultas têm que produzir o MESMO relatório no banco que as cronometra.

    Esta não é a segunda metade do gate: correção continua sendo decidida no
    banco adversarial, que é o único com pedido sem item, empate exato e data na
    borda. Esta checagem responde a outra pergunta, que só existe porque gate e
    benchmark são bancos diferentes — *o tempo medido foi gasto produzindo o
    relatório?*

    Sem ela, `... AND (SELECT COUNT(*) FROM orders) < 1000` é verdadeiro nas 18
    linhas do gate e falso nas 120.000 do benchmark: o candidato passa correto e
    é cronometrado devolvendo zero linha. Uma data embutida fora do alcance do
    banco de gate faz o mesmo de forma mais discreta.

    A cópia usa o mesmo prefixo e o mesmo nome de arquivo que as do relógio (ver
    `PREFIXO_COPIA`), e é feita mesmo quando `setup.sql` é vazio: rodar direto no
    arquivo congelado daria às consultas um caminho diferente do cronometrado —
    que é o sinal que elas não podem ter.
    """
    with tempfile.TemporaryDirectory(prefix=PREFIXO_COPIA) as tmp:
        db = Path(tmp) / NOME_COPIA
        shutil.copyfile(data(PERF_DB), db)
        try:
            rodar_setup(db, setup_sql)
        except sqlite3.Error as exc:
            return (
                False,
                f"{SETUP_FILE} falhou no banco de performance: {type(exc).__name__}: {exc}",
            )

        for rotulo, lote in LOTES_MEDIDOS:
            for nome in NOMES:
                params = lote[nome]
                onde = f"{nome} no lote {rotulo}, janela [{params['d0']}, {params['d1']})"
                try:
                    n_cols, linhas = rodar_consulta(db, consultas[nome], params)
                except sqlite3.Error as exc:
                    return False, f"{onde} no banco de performance: {type(exc).__name__}: {exc}"
                esp_cols, esp_linhas, esp_hash = esperado_perf(nome, params)
                obtido = (n_cols, len(linhas), contracts.canon_hash_rows(linhas))
                if obtido == (esp_cols, esp_linhas, esp_hash):
                    continue
                if n_cols != esp_cols:
                    divergencia = f"{n_cols} colunas, esperadas {esp_cols}"
                elif len(linhas) != esp_linhas:
                    divergencia = f"{len(linhas)} linhas, esperadas {esp_linhas}"
                else:
                    divergencia = f"{esp_linhas} linhas com conteúdo divergente"
                return False, (
                    f"{onde}: no banco de performance a consulta devolveu {divergencia}. Ela "
                    "passou no banco de gate e falha aqui, o que quer dizer que o resultado "
                    "depende de QUAL banco está sendo lido — data embutida, predicado sobre o "
                    "tamanho da tabela, ou corte que só vale na cardinalidade do gate. O tempo "
                    "medido tem que ser o tempo de produzir o relatório."
                )
    return True, "ok"


def judge_medicao(candidato) -> tuple[bool, str]:
    """O gate mais a consistência no banco medido, num julgador só.

    `main` roda as duas separadamente para que a reprovação diga qual falhou.
    Aqui vêm juntas porque `--selftest` precisa de um `Gate` único para julgar os
    mutantes `trapaca_*`: cada um deles passa no gate e é a segunda metade que os
    pega.
    """
    ok, detalhe = GATE.check(candidato)
    if not ok:
        return False, detalhe
    setup_sql, consultas = candidato()
    return checar_consistencia_perf(setup_sql, consultas)


GATE_MEDICAO = evalkit.Gate(
    judge=judge_medicao, description="gate + os oito relatórios conferidos no banco cronometrado"
)

#: Trapaças: corretas no banco de gate, vazias no banco que as cronometra.
#: Nenhuma erra uma conta — todas erram a pergunta. O gate sozinho aprova as
#: cinco, e por isso elas são julgadas por `GATE_MEDICAO`.
TRAPACAS = (
    (
        "trapaca_conta_linhas_da_tabela",
        plano(
            "",
            {
                "q1_receita_mensal": _troca(
                    Q1,
                    "o.order_date < :d1",
                    "o.order_date < :d1 AND (SELECT COUNT(*) FROM orders) < 1000",
                )
            },
        ),
    ),
    (
        "trapaca_reconhece_o_banco_pela_pk",
        plano(
            "",
            {
                "q3_ranking_regiao": _troca(
                    Q3,
                    "o.order_date < :d1",
                    "o.order_date < :d1 AND (SELECT MAX(order_id) FROM orders) < 1000",
                )
            },
        ),
    ),
    # A mais perigosa por ser a mais discreta: uma única data literal, plausível
    # como "poda", que o banco de gate não tem como enxergar porque os dados dele
    # acabam em 2024-04-10.
    (
        "trapaca_data_embutida_fora_do_gate",
        plano(
            "",
            {
                "q8_conciliacao_diaria": _troca(
                    Q8,
                    "FROM orders o WHERE o.order_date >= :d0",
                    "FROM orders o WHERE o.order_date < '2024-05-01' AND o.order_date >= :d0",
                )
            },
        ),
    ),
    # A trapaça de segunda ordem, a que sobreviveria à conferência no banco
    # medido: em vez de olhar o conteúdo, olha o CAMINHO.
    (
        "trapaca_le_o_caminho_do_arquivo",
        plano(
            "",
            {
                "q5_canal_ou_pais": _troca(
                    Q5,
                    "o.status = 'delivered' AND o.order_date >= :d0 AND o.order_date < :d1 "
                    "AND o.channel = :canal",
                    "o.status = 'delivered' AND o.order_date >= :d0 AND o.order_date < :d1 "
                    "AND o.channel = :canal AND (SELECT file FROM pragma_database_list WHERE seq = 0) "
                    "LIKE '%gate%'",
                )
            },
        ),
    ),
    # A mesma coisa escondida atrás de uma view: o `setup.sql` precisa recusar
    # pelo mesmo motivo, senão a consulta lê o ambiente sem nomear `pragma`.
    (
        "trapaca_caminho_escondido_numa_view",
        plano(
            "CREATE VIEW ambiente AS SELECT file AS arquivo FROM pragma_database_list WHERE seq = 0;",
            {
                "q4_clientes_inativos": _troca(
                    Q4,
                    "WHERE c.signup_date < :d1",
                    "WHERE (SELECT arquivo FROM ambiente) LIKE '%gate%' AND c.signup_date < :d1",
                )
            },
        ),
    ),
)


def selftest_trapacas(stream=sys.stdout) -> bool:
    """Segunda tabela do `--selftest`: as trapaças que só o banco medido pega."""
    ok_ref, detalhe = GATE_MEDICAO.check(plano(""))
    rotulo = "CONSISTÊNCIA da referência no banco medido (deve passar)"
    print(f"  {'PASS' if ok_ref else 'FAIL':4}  {rotulo:46} {detalhe[:68]}", file=stream)

    sobreviventes = []
    for nome, candidato in TRAPACAS:
        ok, detalhe = GATE_MEDICAO.check(candidato)
        if ok:
            sobreviventes.append(nome)
        print(
            f"  {'PASS' if ok else 'FAIL':4}  {f'mutante {nome} (deve falhar)':46} {detalhe[:68]}",
            file=stream,
        )
    return ok_ref and not sobreviventes


# ------------------------------------------------------------------- medição

#: Este alvo não usa as camadas anti-memoização do labkit (caminho novo e módulo
#: novo a cada execução): o candidato aqui é SQL, não um módulo Python, e não há
#: estado de processo para sobreviver entre execuções — cada execução abre uma
#: conexão nova sobre uma cópia nova do banco congelado. Guardar a resposta numa
#: tabela é fechado no gate: `setup.sql` recusa CREATE TABLE e cada consulta só
#: aceita um comando SELECT/WITH.
#:
#: O que NÃO é fechado por nada disso, e por isso existe `checar_consistencia_perf`:
#: a consulta pode reconhecer em qual banco está. Ver os mutantes `trapaca_*`.
#:
#: O nome desta constante é verificado por tests/test_anticheat.py, que exige das
#: alternativas: ou o alvo usa as camadas, ou declara aqui por que não precisa.
SEM_DEFESA_DE_MEDICAO = (
    "candidato e SQL: nao ha modulo Python para memoizar; a trapaca equivalente "
    "(reconhecer o banco e devolver relatorio vazio no medido) e fechada por "
    "checar_consistencia_perf"
)


def _rodar_lote(db: Path, consultas: dict[str, str], lote: dict[str, dict]) -> None:
    for nome in NOMES:
        rodar_consulta(db, consultas[nome], lote[nome])


def medir(
    setup_sql: str, consultas: dict[str, str], repeats: int = 4, warmup: int = 1
) -> evalkit.Measurement:
    """Mede os três regimes. A cópia do banco fica FORA do relógio.

    Isto não usa `evalkit.measure` porque cada execução do regime frio precisa de
    um banco recém-copiado, e essa preparação não pode entrar na conta: o que se
    quer medir é `setup.sql` mais os oito relatórios, não a velocidade do `cp`.
    O resultado é montado no mesmo `Measurement` do resto do laboratório, então
    mediana, coeficiente de variação e `notes()` continuam idênticos.
    """
    medida = evalkit.Measurement()
    inicio = time.perf_counter()
    congelado = data(PERF_DB)

    with (
        tempfile.TemporaryDirectory(prefix=PREFIXO_COPIA) as tmp_frio,
        tempfile.TemporaryDirectory(prefix=PREFIXO_COPIA) as tmp_quente,
    ):
        # Dois diretórios em vez de dois nomes de arquivo: ver `PREFIXO_COPIA`.
        frio_db = Path(tmp_frio) / NOME_COPIA
        quente_db = Path(tmp_quente) / NOME_COPIA

        # frio: banco virgem a cada execução, setup.sql cronometrado junto.
        corridas: list[float] = []
        for i in range(warmup + repeats):
            shutil.copyfile(congelado, frio_db)
            marca = time.perf_counter()
            rodar_setup(frio_db, setup_sql)
            _rodar_lote(frio_db, consultas, LOTE)
            gasto = time.perf_counter() - marca
            if i >= warmup:
                corridas.append(gasto)
        medida.raw["frio"] = corridas
        medida.per_regime["frio"] = statistics.median(corridas)

        # quente e estreito: banco já preparado, só as consultas no relógio.
        shutil.copyfile(congelado, quente_db)
        rodar_setup(quente_db, setup_sql)
        for nome, lote in (("quente", LOTE), ("estreito", LOTE_ESTREITO)):
            corridas = []
            for i in range(warmup + repeats):
                marca = time.perf_counter()
                _rodar_lote(quente_db, consultas, lote)
                gasto = time.perf_counter() - marca
                if i >= warmup:
                    corridas.append(gasto)
            medida.raw[nome] = corridas
            medida.per_regime[nome] = statistics.median(corridas)

    medida.wall_s = time.perf_counter() - inicio
    return medida


def ler_candidato(workdir: str | None) -> tuple[str, dict[str, str]]:
    """Lê `setup.sql` e as oito consultas de um diretório de trabalho."""
    if not workdir:
        raise SystemExit("--workdir é obrigatório (ou use --selftest/--baselines/--budget)")
    raiz = Path(workdir)
    faltando = [a for a in ARQUIVOS if not (raiz / a).exists()]
    if faltando:
        raise FileNotFoundError(
            f"faltam {len(faltando)} consulta(s) em {workdir}: {', '.join(faltando)}"
        )
    setup = raiz / SETUP_FILE
    consultas = {nome: (raiz / f"{nome}.sql").read_text(encoding="utf-8") for nome in NOMES}
    return (setup.read_text(encoding="utf-8") if setup.exists() else ""), consultas


# ----------------------------------------------------------------------- main


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
        passou, linhas = MUTANTS.run(GATE)
        for nome, ok, detalhe in linhas:
            print(f"  {'PASS' if ok else 'FAIL':4}  {nome:46} {detalhe[:68]}")
        # Segunda tabela: as trapaças. Elas não entram na `MutantSuite` porque
        # cada uma custa uma execução no banco de 37 MB — misturá-las faria o
        # `--selftest`, que roda em hook e em CI, passar de segundos para minutos
        # sem descobrir nada sobre os vinte mutantes de semântica.
        passou = passou and selftest_trapacas()
        print(f"\nGATE SELFTEST: {'OK' if passou else 'GATE FURADO'}")
        return 0 if passou else 1

    if args.budget:
        # Mede o SEED, nunca a referência: é o seed que o agente paga no primeiro
        # passo, e dimensionar pelo candidato rápido foi exatamente a Falha 2.
        setup_seed, consultas_seed = ler_candidato(str(HERE / "seed"))
        seed = medir(setup_seed, consultas_seed, repeats=3, warmup=1)
        rapido = medir(SETUP_RAPIDO, REFERENCIA, repeats=3, warmup=1)
        saudavel, mensagem = evalkit.budget_report(seed.wall_s, min(rapido.per_regime.values()))
        print(mensagem)
        print(f"  seed:              {seed.notes()}")
        print(f"  referencia+indice: {rapido.notes()}")
        return 0 if saudavel else 1

    if args.baselines:
        # Duas marcas com significados diferentes: o ponto de partida e o
        # fechamento que um engenheiro escreveria à mão sem tocar no esquema.
        setup_seed, consultas_seed = ler_candidato(str(HERE / "seed"))
        evalkit.emit_baselines(
            {
                "seed": medir(setup_seed, consultas_seed, repeats=3, warmup=1).throughput(),
                "referencia_sem_indice": medir("", REFERENCIA, repeats=3, warmup=1).throughput(),
            }
        )
        return 0

    try:
        setup_sql, consultas = ler_candidato(args.workdir)
    except (FileNotFoundError, OSError, UnicodeDecodeError) as exc:
        evalkit.emit_failure(f"{type(exc).__name__}: {exc}")
        return 0

    candidato = plano(setup_sql, consultas)
    ok_gate, detalhe = GATE.check(candidato)
    if not ok_gate:
        evalkit.emit_failure(f"gate: {detalhe}")
        return 0

    ok_perf, detalhe = checar_consistencia_perf(setup_sql, consultas)
    if not ok_perf:
        evalkit.emit_failure(f"consistência no banco medido: {detalhe}")
        return 0

    try:
        medida = medir(setup_sql, consultas)
    except sqlite3.Error as exc:
        evalkit.emit_failure(f"falhou durante a medição: {type(exc).__name__}: {exc}")
        return 0

    digest = contracts.canon_hash_rows(
        [
            linha
            for nome in NOMES
            for linha in rodar_consulta(
                data(GATE_DB), consultas[nome], params_para(nome, PARAMS_GATE[0])
            )[1]
        ]
    )[:16]
    evalkit.emit_success(
        medida.throughput(),
        notes=f"gate=ok fingerprint={digest} {medida.notes()}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
