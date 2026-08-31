"""f(x) do target sql_agg — o árbitro. Nunca afrouxe isto para um candidato passar.

O candidato aqui não é código Python: é SQL. `work/` tem dois arquivos, e os dois
são avaliados como um par, porque em banco de dados a consulta e o esquema físico
são a mesma decisão:

  query.sql  a consulta medida. Um único `SELECT`/`WITH`, com parâmetros
             nomeados `:d0`, `:d1` e `:top_n`.
  setup.sql  DDL opcional executada ANTES da consulta e cronometrada junto no
             regime frio. Índice, view e `ANALYZE` — nada que altere dados.

Separação deliberada entre gate e benchmark, a mesma do etl_agg e pelo mesmo
motivo (Falha 1):

  CORREÇÃO    -> data/gate_shop.sqlite. Minúsculo, montado linha a linha, com
                 pedido sem item, estorno maior que a venda, empate exato de
                 receita e datas na borda da janela. É o ÚNICO banco que decide
                 `correct`, e ele é consultado com QUATRO conjuntos de
                 parâmetros diferentes — inclusive um que devolve zero linhas.
  PERFORMANCE -> data/perf_shop.sqlite. Grande, banal, congelado. Só mede tempo.

Rodar o gate com vários conjuntos de parâmetros não é zelo excessivo: é o que
separa "a consulta está certa" de "a consulta acerta esta janela". Uma consulta
com as datas embutidas passaria num conjunto só e continuaria errada.

## O banco congelado nunca é modificado

Cada medição copia o `.sqlite` para um arquivo temporário e roda ali. O original
é congelado e o `dataset.lock.json` precisa continuar valendo; um `CREATE INDEX`
sobre ele invalidaria o lock de todos os lineages de uma vez. A consulta ainda
por cima é executada numa conexão aberta em `mode=ro`, então mesmo um `DELETE`
que escapasse da checagem estática morreria no SQLite.

## Como a correção é decidida

Igualdade exata do result set, incluindo a ORDEM das linhas: o `ORDER BY` é
parte do contrato, e um relatório com as mesmas linhas em outra ordem é outro
relatório. A comparação é `contracts.canon_hash_rows`.

Ponto flutuante não entra nessa conta por decisão de projeto: todo dinheiro é
`INTEGER` em centavos, então `SUM` é exato e independente da ordem em que o
planejador visita as linhas. O único valor derivado com ponto flutuante,
`pct_estorno`, é `ROUND(100.0 * estorno / bruto, 2)` sobre duas somas inteiras já
fechadas — uma expressão determinística sobre dois inteiros, não uma acumulação.
Por isso o gate pode exigir igualdade e ainda assim julgar a lógica do candidato
em vez do último bit da mantissa. Ver `kb/00-contrato.md`.

O hash sozinho não ensina nada a quem foi reprovado, então antes dele vêm as
checagens que produzem mensagem útil: número de colunas, número de linhas, e a
primeira linha (e coluna) divergente com o esperado e o obtido lado a lado.

## Por que o banco de performance TAMBÉM é conferido

Separar o gate do benchmark abre um buraco que não existe quando os dois são o
mesmo dado: a consulta pode reconhecer em qual banco está e devolver o relatório
certo só no pequeno. `... AND (SELECT COUNT(*) FROM orders) < 1000` passa nas
quatro janelas do gate (35 pedidos) e devolve ZERO linha em cada regime medido
(60.000 pedidos) — tempo de sobra, relatório nenhum. Medido antes desta defesa:
16,2 contra 1,6 do seed, dez vezes o seed e duas vezes e meia o melhor candidato
honesto que este laboratório conseguiu escrever. Uma data embutida fora do
alcance do banco de gate (que só tem dezembro/2023 a abril/2024) faz o mesmo de
forma mais discreta, esvaziando três dos quatro trimestres do lote.

Por isso `checar_consistencia_perf` roda o candidato nas CINCO janelas que o
relógio cronometra, no banco grande, e exige o mesmo result set da referência.
Isso não move o gate para o banco de performance — quem decide *correção* segue
sendo o banco adversarial, que é o único com pedido sem item, empate exato e
data na borda. O que esta checagem decide é outra coisa: que o relatório
cronometrado é o relatório. É o análogo, para um alvo de SQL, do
`implausible_speed` dos alvos de Python.
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

ENTRYPOINT = "query.sql"
SETUP_FILE = "setup.sql"

PERF_DB = "perf_shop.sqlite"
GATE_DB = "gate_shop.sqlite"

#: As quatro janelas do lote medido: os trimestres de 2024, na ordem em que um
#: fechamento anual os roda. O regime frio paga `setup.sql` uma vez e as quatro
#: consultas em seguida — é assim que um índice tem chance de se pagar, e é
#: também o que impede que criar índice do mundo inteiro seja de graça.
LOTE = (
    {"d0": "2024-01-01", "d1": "2024-04-01", "top_n": 20},
    {"d0": "2024-04-01", "d1": "2024-07-01", "top_n": 20},
    {"d0": "2024-07-01", "d1": "2024-10-01", "top_n": 20},
    {"d0": "2024-10-01", "d1": "2025-01-01", "top_n": 20},
)

#: A janela larga: 2023 inteiro de uma vez, com corte mais fundo. Existe para
#: punir a consulta que só serve para um trimestre — um plano afinado para uma
#: faixa curta costuma degradar quando a faixa cresce doze vezes.
JANELA_LARGA = {"d0": "2023-01-01", "d1": "2024-01-01", "top_n": 40}

#: Conjuntos de parâmetros do gate. O último devolve zero linhas de propósito:
#: um result set vazio ainda tem que ter o número certo de colunas, e candidato
#: que estoura em janela vazia é candidato errado.
PARAMS_GATE = (
    {"d0": "2024-01-01", "d1": "2024-04-01", "top_n": 5},
    {"d0": "2024-02-01", "d1": "2024-03-01", "top_n": 3},
    {"d0": "2023-12-01", "d1": "2024-06-01", "top_n": 50},
    {"d0": "2024-06-01", "d1": "2024-07-01", "top_n": 5},
)

#: Toda cópia que o candidato chega a enxergar — a do gate, a da conferência no
#: banco medido e as duas do relógio — é criada com ESTE prefixo de diretório e
#: ESTE nome de arquivo. Não é cosmético e não deve ser "arrumado": é o que
#: impede que a consulta descubra pelo caminho se está sendo julgada, conferida
#: ou cronometrada, e devolva o relatório certo só onde é julgada. As funções
#: `pragma_*` que exporiam o caminho já são recusadas na checagem estática;
#: isto é a segunda linha, a que continua valendo se alguém achar outra porta.
#: Com nomes iguais, o único sinal que distingue os bancos é o CONTEÚDO — e usar
#: o conteúdo para mudar a resposta é exatamente o que `checar_consistencia_perf`
#: reprova.
PREFIXO_COPIA = "sql_agg_copia_"
NOME_COPIA = "copia.sqlite"

#: Teto de tempo de parede para UMA execução de SQL, em segundos. Não é
#: orçamento de score: é o freio que impede um candidato com produto cartesiano
#: de segurar o harness por dez minutos. Generoso o bastante para que nenhuma
#: consulta honesta chegue perto.
LIMITE_SQL_S = 45.0


#: Este alvo nao usa as camadas anti-memoizacao do labkit (caminho novo e modulo
#: novo a cada execucao): o candidato aqui e SQL, nao um modulo Python, e nao ha
#: estado de processo para sobreviver entre execucoes — cada execucao abre uma
#: conexao nova sobre uma COPIA nova do banco congelado. Guardar a resposta numa
#: tabela e so le-la e fechado no gate: `setup.sql` recusa CREATE TABLE, e
#: `query.sql` so aceita um comando SELECT/WITH.
#:
#: O que NAO e fechado por nada disso, e por isso existe `checar_consistencia_perf`:
#: a consulta pode reconhecer em qual banco esta. Correta no banco de gate,
#: vazia no banco que a cronometra. Nao e memoizacao — e nao fazer o trabalho —
#: e nenhum gate de correcao pega, porque o gate roda no outro banco. Ver os
#: mutantes `trapaca_*`.
#:
#: O nome desta constante e verificado por tests/test_anticheat.py, que exige das
#: alternativas: ou o alvo usa as camadas, ou declara aqui por que nao precisa.
SEM_DEFESA_DE_MEDICAO = (
    "candidato e SQL: nao ha modulo Python para memoizar; a trapaca equivalente "
    "(reconhecer o banco e devolver relatorio vazio no medido) e fechada por "
    "checar_consistencia_perf"
)


def data(name: str) -> Path:
    return datakit.data_dir(HERE) / name


# ----------------------------------------------------- leitura e execução de SQL


def _sem_comentarios(sql: str) -> str:
    """Remove comentários e o conteúdo de literais de texto.

    As checagens estáticas rodam sobre isto, não sobre o SQL cru: senão um
    comentário `-- não use DELETE` ou uma coluna com o texto `'insert'` reprovaria
    um candidato honesto, e um `DROP` escondido dentro de um comentário passaria
    a impressão de ter sido inspecionado quando não foi.
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
    limpo = _sem_comentarios(sql)
    partes = [p.strip() for p in limpo.split(";")]
    return [p for p in partes if p]


def _palavras(texto: str) -> set[str]:
    import re

    return set(re.findall(r"[a-z_]+", texto.lower()))


#: Palavras que não podem aparecer em `query.sql`. A conexão de leitura já
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
#: `pragma_database_list`, que não é igual a `pragma`. Elas não leem dado
#: nenhum: leem o AMBIENTE. `pragma_database_list` devolve o caminho do arquivo
#: aberto, e com ele a consulta descobre se está sendo julgada (`gate_shop`),
#: conferida ou cronometrada, e pode devolver o relatório certo só quando é
#: julgada. Foi medido: 10,5x o seed com `correct=true`, devolvendo zero linha
#: em todo regime cronometrado. Ver o mutante `trapaca_le_o_caminho_do_arquivo`.
PREFIXO_PRAGMA = "pragma"


def _funcoes_de_ambiente(texto: str) -> set[str]:
    return {palavra for palavra in _palavras(texto) if palavra.startswith(PREFIXO_PRAGMA)}


def _recusa_ambiente(arquivo: str, achadas: set[str]) -> str:
    return (
        f"{arquivo} usa {', '.join(sorted(achadas)).upper()}: as funções de tabela `pragma_*` "
        "não leem os dados, leem o ambiente — `pragma_database_list` devolve o caminho do "
        "arquivo aberto. Uma consulta que enxerga em QUAL banco está pode acertar o relatório "
        "só onde é julgada e devolver nada onde é cronometrada. O alvo mede a consulta, não o "
        "reconhecimento do arquivo."
    )


def checar_consulta(sql: str) -> tuple[bool, str]:
    """`query.sql` tem que ser UM `SELECT`/`WITH` e nada além disso."""
    cmds = statements(sql)
    if not cmds:
        return False, f"{ENTRYPOINT} está vazio: era esperado um SELECT"
    if len(cmds) > 1:
        return False, (
            f"{ENTRYPOINT} tem {len(cmds)} comandos; é permitido exatamente um. "
            "DDL vai em setup.sql, e só índice, view ou ANALYZE."
        )
    primeira = cmds[0].split()[0].lower() if cmds[0].split() else ""
    if primeira not in ("select", "with"):
        return False, (
            f"{ENTRYPOINT} começa com {primeira.upper()!r}; a consulta avaliada tem que ser "
            "um SELECT (podendo abrir com WITH)."
        )
    ambiente = _funcoes_de_ambiente(cmds[0]) - {PREFIXO_PRAGMA}
    if ambiente:
        return False, _recusa_ambiente(ENTRYPOINT, ambiente)
    achadas = _palavras(cmds[0]) & set(PROIBIDO_NA_CONSULTA)
    if achadas:
        return False, (
            f"{ENTRYPOINT} contém {', '.join(sorted(achadas)).upper()}: a consulta medida só "
            "pode ler. Índice e view vão em setup.sql."
        )
    return True, "ok"


def checar_setup(sql: str) -> tuple[bool, str]:
    """`setup.sql` só pode preparar o banco, nunca mudar o que ele responde.

    A lista é curta de propósito. Materializar o resultado numa tabela faria o
    número subir sem que consulta nenhuma tivesse ficado melhor — é a forma que
    reward hacking assume neste alvo, e ela é recusada aqui pelo nome.
    """
    permitidos = ("analyze", "create index ", "create unique index ", "create view ")
    for cmd in statements(sql):
        low = " ".join(cmd.lower().split())
        # Antes do allowlist: uma `CREATE VIEW v AS SELECT file FROM
        # pragma_database_list` é um CREATE VIEW legítimo pelo prefixo e
        # entrega à consulta exatamente o que a consulta não pode ver.
        ambiente = _funcoes_de_ambiente(low) - {PREFIXO_PRAGMA}
        if ambiente:
            return False, _recusa_ambiente(SETUP_FILE, ambiente)
        if low.startswith(permitidos):
            continue
        if low.startswith("create table") or low.startswith("create virtual table"):
            return False, (
                f"{SETUP_FILE}: CREATE TABLE não é aceito. Guardar o resultado numa tabela faz "
                "o score subir sem que nenhuma consulta tenha ficado melhor — o alvo mede a "
                "consulta, não a memorização dela."
            )
        if low.startswith(("create temp ", "create temporary ")):
            return False, (
                f"{SETUP_FILE}: objeto temporário morre junto com a conexão de setup e não "
                "existiria na hora da consulta. Crie um índice permanente."
            )
        if low.startswith("pragma"):
            return False, (
                f"{SETUP_FILE}: PRAGMA vale só para a conexão que o executou, e a consulta roda "
                "em outra. Não teria efeito nenhum na medição."
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
    """Executa a consulta numa conexão SOMENTE LEITURA e devolve (n_colunas, linhas)."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        _freio(conn)
        cur = conn.execute(sql, params)
        linhas = cur.fetchall()
        n_cols = len(cur.description or ())
    finally:
        conn.close()
    return n_cols, linhas


# ----------------------------------------------------------------- referência

REFERENCIA = """
WITH ped AS (
    SELECT o.order_id AS order_id, o.customer_id AS customer_id,
           substr(o.order_date, 1, 7) AS mes
    FROM orders o
    WHERE o.status = 'delivered'
      AND o.order_date >= :d0
      AND o.order_date < :d1
),
det AS (
    SELECT p.mes AS mes, p.customer_id AS customer_id, p.order_id AS order_id,
           COALESCE(SUM(i.qty * i.unit_cents), 0) AS bruto
    FROM ped p
    LEFT JOIN order_items i ON i.order_id = p.order_id
    GROUP BY p.order_id
),
agg AS (
    SELECT d.mes AS mes,
           d.customer_id AS customer_id,
           COUNT(*) AS n_pedidos,
           SUM(CASE WHEN r.order_id IS NULL THEN 0 ELSE 1 END) AS n_estornos,
           SUM(d.bruto) AS bruto_cents,
           SUM(COALESCE(r.amount_cents, 0)) AS estorno_cents,
           SUM(d.bruto) - SUM(COALESCE(r.amount_cents, 0)) AS liquido_cents
    FROM det d
    LEFT JOIN refunds r ON r.order_id = d.order_id
    GROUP BY d.mes, d.customer_id
),
rk AS (
    SELECT a.*, RANK() OVER (PARTITION BY a.mes ORDER BY a.liquido_cents DESC) AS rank_mes
    FROM agg a
)
SELECT g.mes,
       g.customer_id,
       (SELECT c.region FROM customers c WHERE c.customer_id = g.customer_id) AS region,
       g.n_pedidos,
       g.n_estornos,
       g.bruto_cents,
       g.estorno_cents,
       g.liquido_cents,
       CASE WHEN g.bruto_cents > 0
            THEN ROUND(100.0 * g.estorno_cents / g.bruto_cents, 2)
            ELSE 0.0 END AS pct_estorno,
       g.rank_mes
FROM rk g
WHERE g.rank_mes <= :top_n
ORDER BY g.mes DESC, g.liquido_cents DESC, g.customer_id
"""

#: O melhor par (setup, consulta) que este laboratório encontrou à mão. Serve só
#: para estimar em `--budget` a execução mais rápida imaginável — o piso de
#: ruído tem que ficar abaixo dela. Não aparece nas baselines nem na KB: achar
#: a forma do índice é parte do problema.
SETUP_RAPIDO = (
    "CREATE INDEX ix_ord ON orders(order_id, order_date, customer_id)\n"
    "    WHERE status = 'delivered';"
)


def plano(setup: str, query: str):
    """Empacota um par (setup, consulta) como o `MutantSuite` espera: um chamável."""

    def _plano() -> tuple[str, str]:
        return setup, query

    return _plano


_ESPERADO: dict[str, tuple[int, list[tuple]]] = {}


def esperado(params: dict) -> tuple[int, list[tuple]]:
    chave = f"{params['d0']}|{params['d1']}|{params['top_n']}"
    if chave not in _ESPERADO:
        _ESPERADO[chave] = rodar_consulta(data(GATE_DB), REFERENCIA, params)
    return _ESPERADO[chave]


# ----------------------------------------------------------------------- gate


def _celula(valor) -> str:
    """A mesma normalização que `canon_hash_rows(places=6)` aplica.

    Existe só para a mensagem de erro: quem decide é o hash, mas "hash divergente"
    não diz ao agente o que consertar. Com isto a rejeição nomeia a linha, a
    coluna, o esperado e o obtido.
    """
    if isinstance(valor, float):
        return f"{valor:.6f}"
    return str(valor)


def comparar(params: dict, n_cols: int, linhas: list[tuple]) -> tuple[bool, str]:
    esp_cols, esp_linhas = esperado(params)
    janela = f"[{params['d0']}, {params['d1']}) top_n={params['top_n']}"

    if n_cols != esp_cols:
        return False, (
            f"janela {janela}: {n_cols} colunas, esperadas {esp_cols}. A ordem e o conjunto "
            "de colunas fazem parte do contrato (kb/00-contrato.md)."
        )
    if len(linhas) != len(esp_linhas):
        return False, (
            f"janela {janela}: {len(linhas)} linhas, esperadas {len(esp_linhas)}. "
            "Linha a mais costuma ser filtro de data ou de status frouxo; linha a menos, "
            "LEFT JOIN virado em INNER."
        )
    if contracts.canon_hash_rows(linhas) == contracts.canon_hash_rows(esp_linhas):
        return True, "ok"

    for i, (obtida, esp) in enumerate(zip(linhas, esp_linhas, strict=True)):
        if [_celula(v) for v in obtida] != [_celula(v) for v in esp]:
            for j, (a, b) in enumerate(zip(obtida, esp, strict=True)):
                if _celula(a) != _celula(b):
                    return False, (
                        f"janela {janela}: linha {i} coluna {j} divergente — "
                        f"esperado {b!r}, obtido {a!r}. Linha esperada: {esp!r}"
                    )
            return False, f"janela {janela}: linha {i} divergente — esperada {esp!r}"
    return False, f"janela {janela}: hash divergente sem célula divergente (tipos?)"


def judge(candidato) -> tuple[bool, str]:
    """Roda o par (setup, consulta) no banco adversarial e decide `correct`."""
    setup_sql, query_sql = candidato()

    ok, detalhe = checar_setup(setup_sql)
    if not ok:
        return False, detalhe
    ok, detalhe = checar_consulta(query_sql)
    if not ok:
        return False, detalhe

    with tempfile.TemporaryDirectory(prefix=PREFIXO_COPIA) as tmp:
        db = Path(tmp) / NOME_COPIA
        shutil.copyfile(data(GATE_DB), db)
        try:
            rodar_setup(db, setup_sql)
        except sqlite3.Error as exc:
            return False, f"{SETUP_FILE} falhou: {type(exc).__name__}: {exc}"
        for params in PARAMS_GATE:
            try:
                n_cols, linhas = rodar_consulta(db, query_sql, params)
            except sqlite3.Error as exc:
                return False, (
                    f"janela [{params['d0']}, {params['d1']}) top_n={params['top_n']}: "
                    f"{type(exc).__name__}: {exc}"
                )
            ok, detalhe = comparar(params, n_cols, linhas)
            if not ok:
                return False, detalhe
    return True, "ok"


GATE = evalkit.Gate(judge=judge, description="banco adversarial, quatro janelas, ordem exata")


# ------------------------------------- o relatório cronometrado é o relatório?

#: As cinco janelas que o relógio de fato executa: as quatro do lote mais a
#: larga. É sobre ESTAS que a consistência no banco de performance é exigida —
#: qualquer outra janela seria conferir o que ninguém mediu.
JANELAS_MEDIDAS = (*LOTE, JANELA_LARGA)

_ESPERADO_PERF: dict[str, tuple[int, int, str]] = {}


def _chave(params: dict) -> str:
    return f"{params['d0']}|{params['d1']}|{params['top_n']}"


def esperado_perf(params: dict) -> tuple[int, int, str]:
    """`(n_colunas, n_linhas, hash)` da referência no banco de performance.

    Calculado uma vez por processo, direto no arquivo congelado — a conexão é
    somente leitura e quem roda aqui é a REFERÊNCIA, que não tem interesse em
    descobrir onde está. Custa uma execução da referência por janela e é pago
    fora de qualquer relógio.
    """
    chave = _chave(params)
    if chave not in _ESPERADO_PERF:
        n_cols, linhas = rodar_consulta(data(PERF_DB), REFERENCIA, params)
        _ESPERADO_PERF[chave] = (n_cols, len(linhas), contracts.canon_hash_rows(linhas))
    return _ESPERADO_PERF[chave]


def checar_consistencia_perf(setup_sql: str, query_sql: str) -> tuple[bool, str]:
    """A consulta tem que produzir o MESMO relatório no banco que a cronometra.

    Esta não é a segunda metade do gate: correção continua sendo decidida no
    banco adversarial, que é o único que tem pedido sem item, empate exato e
    data na borda. Esta checagem responde a outra pergunta, que só existe porque
    gate e benchmark são bancos diferentes — *o tempo medido foi gasto
    produzindo o relatório?*

    Sem ela, `... AND (SELECT COUNT(*) FROM orders) < 1000` é verdadeiro nas 35
    linhas do gate e falso nas 60.000 do benchmark: o candidato passa correto e
    é cronometrado devolvendo zero linha — dez vezes o score do seed, duas vezes
    e meia o do melhor candidato honesto. Uma data embutida fora do intervalo do
    banco de gate faz o mesmo mais discretamente.

    A cópia usa o mesmo prefixo e o mesmo nome de arquivo que as do relógio (ver
    `PREFIXO_COPIA`), e é feita mesmo quando `setup.sql` é vazio: rodar direto no
    arquivo congelado economizaria 60 ms e daria à consulta um caminho diferente
    do cronometrado — que é o sinal que ela não pode ter.
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

        for params in JANELAS_MEDIDAS:
            janela = f"[{params['d0']}, {params['d1']}) top_n={params['top_n']}"
            try:
                n_cols, linhas = rodar_consulta(db, query_sql, params)
            except sqlite3.Error as exc:
                return False, (
                    f"janela medida {janela} no banco de performance: {type(exc).__name__}: {exc}"
                )
            esp_cols, esp_linhas, esp_hash = esperado_perf(params)
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
                f"janela medida {janela}: no banco de performance a consulta devolveu "
                f"{divergencia}. Ela passou no banco de gate e falha aqui, o que quer dizer "
                "que o resultado depende de QUAL banco está sendo lido — data embutida, "
                "predicado sobre o tamanho da tabela, ou corte que só vale na cardinalidade "
                "do gate. O tempo medido tem que ser o tempo de produzir o relatório."
            )
    return True, "ok"


def judge_medicao(candidato) -> tuple[bool, str]:
    """O gate mais a consistência no banco medido, num julgador só.

    `main` roda as duas separadamente, para que a reprovação diga qual das duas
    falhou. Aqui elas vêm juntas porque `--selftest` precisa de um `Gate` único
    para julgar os mutantes `trapaca_*`: cada um deles passa no gate e é a
    segunda metade que os pega.
    """
    ok, detalhe = GATE.check(candidato)
    if not ok:
        return False, detalhe
    setup_sql, query_sql = candidato()
    return checar_consistencia_perf(setup_sql, query_sql)


GATE_MEDICAO = evalkit.Gate(
    judge=judge_medicao, description="gate + o relatório conferido no banco cronometrado"
)


# ------------------------------------------------------------------- mutantes


def _troca(original: str, alvo: str, novo: str) -> str:
    """`str.replace` que grita quando o alvo sumiu.

    Os mutantes são derivados da referência por substituição. Se uma edição da
    referência apagar o trecho que um mutante altera, o mutante viraria uma cópia
    da referência — passaria no gate e o `--selftest` acusaria "gate furado" sem
    dizer que o problema é o mutante, não o gate.
    """
    if alvo not in original:
        raise AssertionError(f"trecho ausente na referência: {alvo[:60]!r}")
    return original.replace(alvo, novo, 1)


M_INNER_ESTORNO = _troca(REFERENCIA, "LEFT JOIN refunds r", "JOIN refunds r")
M_INNER_ITENS = _troca(REFERENCIA, "LEFT JOIN order_items i", "JOIN order_items i")
M_SEM_MES = _troca(REFERENCIA, "GROUP BY d.mes, d.customer_id", "GROUP BY d.customer_id")
M_ORDEM_ERRADA = _troca(
    REFERENCIA,
    "ORDER BY g.mes DESC, g.liquido_cents DESC, g.customer_id",
    "ORDER BY g.mes DESC, g.customer_id",
)
#: Sem ORDER BY nenhum. A função de janela já obriga o SQLite a ordenar por
#: (mes, líquido DESC) para calcular o RANK, então o result set sai quase certo
#: por acaso -- e é exatamente por isso que o contrato pede o mês DESCENDENTE:
#: a ordem que o plano entrega de graça não pode ser a ordem contratada, senão o
#: gate não estaria verificando ordem nenhuma, só fingindo.
M_SEM_ORDEM = _troca(REFERENCIA, "ORDER BY g.mes DESC, g.liquido_cents DESC, g.customer_id", "")
M_CONTA_NULO = _troca(
    REFERENCIA,
    "SUM(CASE WHEN r.order_id IS NULL THEN 0 ELSE 1 END) AS n_estornos",
    "COUNT(*) AS n_estornos",
)
M_DATA_INCLUSIVA = _troca(REFERENCIA, "AND o.order_date < :d1", "AND o.order_date <= :d1")
M_STATUS_FROUXO = _troca(
    REFERENCIA, "WHERE o.status = 'delivered'", "WHERE o.status <> 'cancelled'"
)
M_ROW_NUMBER = _troca(REFERENCIA, "RANK() OVER", "ROW_NUMBER() OVER")
M_PCT_SEM_GUARDA = _troca(
    REFERENCIA,
    """CASE WHEN g.bruto_cents > 0
            THEN ROUND(100.0 * g.estorno_cents / g.bruto_cents, 2)
            ELSE 0.0 END AS pct_estorno""",
    "ROUND(100.0 * g.estorno_cents / g.bruto_cents, 2) AS pct_estorno",
)

#: Arredondar por pedido e tirar a média em vez de arredondar a razão das somas.
#: É o erro de arredondamento "no lugar errado" traduzido para SQL.
M_PCT_POR_PEDIDO = _troca(
    _troca(
        REFERENCIA,
        "           SUM(d.bruto) - SUM(COALESCE(r.amount_cents, 0)) AS liquido_cents",
        "           SUM(d.bruto) - SUM(COALESCE(r.amount_cents, 0)) AS liquido_cents,\n"
        "           ROUND(AVG(CASE WHEN d.bruto > 0\n"
        "                          THEN 100.0 * COALESCE(r.amount_cents, 0) / d.bruto\n"
        "                          ELSE 0.0 END), 2) AS pct_por_pedido",
    ),
    """CASE WHEN g.bruto_cents > 0
            THEN ROUND(100.0 * g.estorno_cents / g.bruto_cents, 2)
            ELSE 0.0 END AS pct_estorno""",
    "g.pct_por_pedido AS pct_estorno",
)

#: Junta `refunds` no mesmo nível dos itens: o estorno é somado uma vez por item
#: do pedido. É o erro de fan-out, e ele só aparece em pedido com mais de um item
#: E com estorno — por isso o banco de gate tem exatamente essa linha plantada.
M_FAN_OUT = _troca(
    _troca(
        REFERENCIA,
        """    SELECT p.mes AS mes, p.customer_id AS customer_id, p.order_id AS order_id,
           COALESCE(SUM(i.qty * i.unit_cents), 0) AS bruto
    FROM ped p
    LEFT JOIN order_items i ON i.order_id = p.order_id
    GROUP BY p.order_id""",
        """    SELECT p.mes AS mes, p.customer_id AS customer_id, p.order_id AS order_id,
           COALESCE(SUM(i.qty * i.unit_cents), 0) AS bruto,
           COALESCE(SUM(r2.amount_cents), 0) AS estorno
    FROM ped p
    LEFT JOIN order_items i ON i.order_id = p.order_id
    LEFT JOIN refunds r2 ON r2.order_id = p.order_id
    GROUP BY p.order_id""",
    ),
    "SUM(COALESCE(r.amount_cents, 0)) AS estorno_cents",
    "SUM(d.estorno) AS estorno_cents",
)
M_FAN_OUT = _troca(
    M_FAN_OUT,
    "SUM(d.bruto) - SUM(COALESCE(r.amount_cents, 0)) AS liquido_cents",
    "SUM(d.bruto) - SUM(d.estorno) AS liquido_cents",
)

#: `LIMIT :top_n` no lugar do corte por posto. É a leitura mais natural de "top
#: N" para quem não reparou que o corte é POR MÊS, e é a primeira coisa que
#: alguém tenta ao ver uma função de janela cara no plano — o `LIMIT` é mais
#: barato e responde outra pergunta.
M_LIMIT_GLOBAL = _troca(
    REFERENCIA,
    "WHERE g.rank_mes <= :top_n\nORDER BY g.mes DESC, g.liquido_cents DESC, g.customer_id",
    "ORDER BY g.mes DESC, g.liquido_cents DESC, g.customer_id\nLIMIT :top_n",
)

#: Comparar o prefixo `YYYY-MM` em vez da data inteira. Parece a reescrita
#: "sargável" barata e muda a janela: com `:d1` no meio de um mês, o mês inteiro
#: entra. O banco de gate tem uma janela assim de propósito.
M_JANELA_POR_MES = _troca(
    REFERENCIA,
    "      AND o.order_date >= :d0\n      AND o.order_date < :d1",
    "      AND substr(o.order_date, 1, 7) >= substr(:d0, 1, 7)\n"
    "      AND substr(o.order_date, 1, 7) <= substr(:d1, 1, 7)",
)

#: Os dois abaixo não erram conta nenhuma: erram as regras. Existem porque o gate
#: precisa provar que as recusa, e porque materializar a resposta é a trapaça
#: que este alvo tem a obrigação de não premiar.
SETUP_MATERIALIZA = (
    "CREATE TABLE resposta AS\n"
    "SELECT 1 AS mes, 1 AS customer_id, 1 AS region, 1 AS n_pedidos, 1 AS n_estornos,\n"
    "       1 AS bruto_cents, 1 AS estorno_cents, 1 AS liquido_cents,\n"
    "       1.0 AS pct_estorno, 1 AS rank_mes;"
)
QUERY_COM_DDL = "CREATE INDEX ix_hack ON orders(order_date);\n" + REFERENCIA


MUTANTS = evalkit.MutantSuite(
    reference=plano("", REFERENCIA),
    mutants=[
        ("estorno_com_inner_join", plano("", M_INNER_ESTORNO)),
        ("itens_com_inner_join", plano("", M_INNER_ITENS)),
        ("group_by_sem_mes", plano("", M_SEM_MES)),
        ("order_by_sem_receita", plano("", M_ORDEM_ERRADA)),
        ("sem_order_by", plano("", M_SEM_ORDEM)),
        ("n_estornos_conta_nulo", plano("", M_CONTA_NULO)),
        ("data_final_inclusiva", plano("", M_DATA_INCLUSIVA)),
        ("status_nao_cancelado", plano("", M_STATUS_FROUXO)),
        ("row_number_no_lugar_de_rank", plano("", M_ROW_NUMBER)),
        ("pct_sem_guarda_de_zero", plano("", M_PCT_SEM_GUARDA)),
        ("pct_arredondado_por_pedido", plano("", M_PCT_POR_PEDIDO)),
        ("fan_out_do_estorno", plano("", M_FAN_OUT)),
        ("top_n_por_limit_global", plano("", M_LIMIT_GLOBAL)),
        ("janela_por_prefixo_de_mes", plano("", M_JANELA_POR_MES)),
        ("setup_materializa_resposta", plano(SETUP_MATERIALIZA, "SELECT * FROM resposta")),
        ("ddl_dentro_da_consulta", plano("", QUERY_COM_DDL)),
    ],
)


#: Trapaças: corretas no banco de gate, vazias (ou quase) no banco que as
#: cronometra. Nenhuma delas erra uma conta — todas erram a pergunta. O gate
#: sozinho aprova as três, e por isso elas são julgadas por `GATE_MEDICAO`.
#:
#: Não são hipotéticas: as três foram escritas, rodadas e pontuaram, com
#: `correct=true`, 4,7x / 6,3x / 10,0x o seed contra os 4,1x do melhor candidato
#: honesto deste laboratório. A terceira é a mais perigosa por ser a mais
#: discreta: uma única data literal, plausível como "poda", que o banco de gate
#: não tem como enxergar porque os dados dele acabam em 2024-04-02.
T_CONTA_PEDIDOS = _troca(
    REFERENCIA,
    "      AND o.order_date < :d1",
    "      AND o.order_date < :d1\n      AND (SELECT COUNT(*) FROM orders) < 1000",
)
T_MAX_ORDER_ID = _troca(
    REFERENCIA,
    "      AND o.order_date < :d1",
    "      AND o.order_date < :d1\n      AND (SELECT MAX(order_id) FROM orders) < 1000",
)
T_DATA_EMBUTIDA = _troca(
    REFERENCIA,
    "      AND o.order_date < :d1",
    "      AND o.order_date < :d1\n      AND o.order_date < '2024-05-01'",
)

#: A trapaça de segunda ordem, a que sobrevive à conferência no banco medido:
#: em vez de olhar o conteúdo, olha o CAMINHO. `pragma_database_list` é uma
#: função de tabela, não o comando `PRAGMA`, então a checagem de palavra não a
#: via. Medida antes da defesa: `correct=true` e 10,5x o seed.
T_CAMINHO = _troca(
    REFERENCIA,
    "      AND o.order_date < :d1",
    "      AND o.order_date < :d1\n"
    "      AND (SELECT file FROM pragma_database_list WHERE seq = 0) LIKE '%_shop.sqlite'",
)

#: A mesma coisa escondida atrás de uma view — o `setup.sql` precisa recusar
#: pelo mesmo motivo, senão a consulta lê o ambiente sem nomear `pragma`.
SETUP_VIEW_AMBIENTE = (
    "CREATE VIEW ambiente AS SELECT file AS arquivo FROM pragma_database_list WHERE seq = 0;"
)
QUERY_LE_A_VIEW = _troca(
    REFERENCIA,
    "      AND o.order_date < :d1",
    "      AND o.order_date < :d1\n      AND (SELECT arquivo FROM ambiente) LIKE '%_shop.sqlite'",
)

TRAPACAS = (
    ("trapaca_conta_linhas_da_tabela", plano("", T_CONTA_PEDIDOS)),
    ("trapaca_reconhece_o_banco_pela_pk", plano("", T_MAX_ORDER_ID)),
    ("trapaca_data_embutida_fora_do_gate", plano("", T_DATA_EMBUTIDA)),
    ("trapaca_le_o_caminho_do_arquivo", plano("", T_CAMINHO)),
    ("trapaca_caminho_escondido_numa_view", plano(SETUP_VIEW_AMBIENTE, QUERY_LE_A_VIEW)),
)


def selftest_trapacas(stream=sys.stdout) -> bool:
    """Segunda tabela do `--selftest`: as trapaças que só o banco medido pega.

    Impressa no mesmo formato da `MutantSuite` porque é essa tabela que o CI
    (`tests/test_gate_teeth.py`) e o revisor humano leem. A linha da referência
    não se chama "REFERÊNCIA" de propósito: a suíte de mutantes já tem a dela, e
    duas aprovações com esse rótulo fariam a checagem "a referência é o único
    PASS" perder o sentido.
    """
    ok_ref, detalhe = GATE_MEDICAO.check(plano("", REFERENCIA))
    rotulo = "CONSISTÊNCIA da referência no banco medido (deve passar)"
    print(f"  {'PASS' if ok_ref else 'FAIL':4}  {rotulo:44} {detalhe[:70]}", file=stream)

    sobreviventes = []
    for nome, candidato in TRAPACAS:
        ok, detalhe = GATE_MEDICAO.check(candidato)
        if ok:
            sobreviventes.append(nome)
        print(
            f"  {'PASS' if ok else 'FAIL':4}  {f'mutante {nome} (deve falhar)':44} {detalhe[:70]}",
            file=stream,
        )
    return ok_ref and not sobreviventes


# ------------------------------------------------------------------- medição


def medir(setup_sql: str, query_sql: str, repeats: int = 4, warmup: int = 1) -> evalkit.Measurement:
    """Mede os três regimes. A cópia do banco fica FORA do relógio.

    Isto não usa `evalkit.measure` porque cada execução do regime frio precisa de
    um banco recém-copiado, e essa preparação não pode entrar na conta: o que se
    quer medir é `setup.sql` mais as consultas, não a velocidade do `cp`. O
    resultado é montado no mesmo `Measurement` do resto do laboratório, então
    mediana, coeficiente de variação e `notes()` continuam idênticos.

    `warmup` descartado: a primeira execução paga cache de página do arquivo
    recém-copiado, e isso é uma constante do sistema, não do candidato.
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
            for params in LOTE:
                rodar_consulta(frio_db, query_sql, params)
            gasto = time.perf_counter() - marca
            if i >= warmup:
                corridas.append(gasto)
        medida.raw["frio"] = corridas
        medida.per_regime["frio"] = statistics.median(corridas)

        # quente e larga: banco já preparado, só a consulta no relógio.
        shutil.copyfile(congelado, quente_db)
        rodar_setup(quente_db, setup_sql)

        for nome, janelas in (("quente", LOTE), ("larga", (JANELA_LARGA,))):
            corridas = []
            for i in range(warmup + repeats):
                marca = time.perf_counter()
                for params in janelas:
                    rodar_consulta(quente_db, query_sql, params)
                gasto = time.perf_counter() - marca
                if i >= warmup:
                    corridas.append(gasto)
            medida.raw[nome] = corridas
            medida.per_regime[nome] = statistics.median(corridas)

    medida.wall_s = time.perf_counter() - inicio
    return medida


def ler_candidato(workdir: str | None) -> tuple[str, str]:
    caminho = evalkit.candidate_path(workdir, ENTRYPOINT)
    if not caminho.exists():
        raise FileNotFoundError(f"{ENTRYPOINT} ausente em {workdir}")
    setup = Path(workdir or ".") / SETUP_FILE
    return (setup.read_text(encoding="utf-8") if setup.exists() else ""), caminho.read_text(
        encoding="utf-8"
    )


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
            print(f"  {'PASS' if ok else 'FAIL':4}  {nome:44} {detalhe[:70]}")
        # Segunda tabela: as trapaças. Elas não entram na `MutantSuite` porque
        # cada uma custa uma execução no banco de 72 MB — misturá-las faria o
        # `--selftest`, que roda em hook e em CI, passar de 0,3s para ~15s sem
        # descobrir nada sobre os quatorze mutantes de semântica.
        passou_trapacas = selftest_trapacas()
        passou = passou and passou_trapacas
        print(f"\nGATE SELFTEST: {'OK' if passou else 'GATE FURADO'}")
        return 0 if passou else 1

    if args.budget:
        # Mede o SEED, nunca a referência: é o seed que o agente paga no primeiro
        # passo, e dimensionar pelo candidato rápido foi exatamente a Falha 2.
        setup_seed, query_seed = ler_candidato(str(HERE / "seed"))
        seed = medir(setup_seed, query_seed, repeats=3, warmup=1)
        rapido = medir(SETUP_RAPIDO, REFERENCIA, repeats=3, warmup=1)
        saudavel, mensagem = evalkit.budget_report(seed.wall_s, min(rapido.per_regime.values()))
        print(mensagem)
        print(f"  seed:              {seed.notes()}")
        print(f"  referencia+indice: {rapido.notes()}")
        return 0 if saudavel else 1

    if args.baselines:
        # Duas marcas com significados diferentes: o ponto de partida e a
        # consulta que um engenheiro escreveria à mão sem mexer no esquema.
        setup_seed, query_seed = ler_candidato(str(HERE / "seed"))
        evalkit.emit_baselines(
            {
                "seed": medir(setup_seed, query_seed, repeats=3, warmup=1).throughput(),
                "referencia_sem_indice": medir("", REFERENCIA, repeats=3, warmup=1).throughput(),
            }
        )
        return 0

    try:
        setup_sql, query_sql = ler_candidato(args.workdir)
    except (FileNotFoundError, OSError, UnicodeDecodeError) as exc:
        evalkit.emit_failure(f"{type(exc).__name__}: {exc}")
        return 0

    ok_gate, detalhe = GATE.check(plano(setup_sql, query_sql))
    if not ok_gate:
        evalkit.emit_failure(f"gate: {detalhe}")
        return 0

    # O gate disse que a consulta está certa no banco pequeno. Falta a pergunta
    # que só o banco grande responde: é o relatório que vai ser cronometrado?
    ok_conf, detalhe = checar_consistencia_perf(setup_sql, query_sql)
    if not ok_conf:
        evalkit.emit_failure(f"consistência no banco medido: {detalhe}")
        return 0

    try:
        medida = medir(setup_sql, query_sql)
    except sqlite3.Error as exc:
        evalkit.emit_failure(f"falhou durante a medição: {type(exc).__name__}: {exc}")
        return 0

    _, linhas = rodar_consulta(data(GATE_DB), query_sql, PARAMS_GATE[0])
    digest = contracts.canon_hash_rows(linhas)[:16]
    evalkit.emit_success(
        medida.throughput(),
        notes=f"gate=ok fingerprint={digest} {medida.notes()}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
