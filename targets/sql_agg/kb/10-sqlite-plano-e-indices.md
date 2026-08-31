# O plano, o custo e o preço de um índice

Números medidos neste banco, nesta máquina. Servem de ordem de grandeza, não de
promessa — a instrução no fim desta página mostra como medir você mesmo.

## O banco de performance

| tabela | linhas | observação |
|---|---|---|
| `customers` | 600 | cabe inteira em cache |
| `orders` | 60.000 | **larga**: doze colunas, ~740 bytes por linha, ~44 MB |
| `order_items` | 719.791 | 6 a 18 itens por pedido, média 12 |
| `refunds` | 7.214 | ~12% dos pedidos |

Dois anos de pedidos, `2023-01-01` a `2024-12-31`, 40.000 deles `delivered`.
`order_id` é uma sequência e cresce junto com `order_date`, como numa tabela de
pedidos de verdade. Uma janela trimestral tem ~5.000 pedidos entregues; a janela
larga (2023 inteiro) tem ~20.000.

Índices que já existem: chaves primárias, `order_items(order_id)` e o implícito
de `refunds(order_id) UNIQUE`. **`orders` não tem índice nenhum além da PK.**

## Ler o plano

```bash
sqlite3 targets/sql_agg/data/perf_shop.sqlite \
  ".param set :d0 '2024-01-01'" ".param set :d1 '2024-04-01'" ".param set :top_n 20" \
  "EXPLAIN QUERY PLAN $(cat work/query.sql)"
```

O que procurar, em ordem de peso:

| linha do plano | significa |
|---|---|
| `SCAN o` | varredura completa de `orders`: 44 MB de páginas de dados lidas |
| `SEARCH o USING COVERING INDEX ...` | o índice bastou; a tabela não foi tocada |
| `SEARCH ... USING INDEX ... (order_id=?)` | busca indexada, barata |
| `CORRELATED SCALAR SUBQUERY n` | executada **uma vez por linha** do laço externo |
| `USE TEMP B-TREE FOR GROUP BY` | as linhas não chegaram na ordem do agrupamento |
| `USE TEMP B-TREE FOR ORDER BY` | ordenação materializada |
| `MATERIALIZE <cte>` | a CTE virou tabela temporária; `CO-ROUTINE` é fluxo |

`SCAN <tabela grande>` e `CORRELATED SCALAR SUBQUERY` são os dois que costumam
explicar a maior parte do tempo.

## O mapa de custo, neste banco

| operação | custo aproximado |
|---|---|
| varrer `orders` inteira com filtro simples | ~22 ms |
| a mesma varredura com `upper()`/`strftime()` sobre a coluna | ~55 ms |
| percorrer um índice cobrindo em vez da tabela | ~2 ms |
| uma busca indexada em `order_items` por `order_id` | ~2 µs |
| construir um índice de 4 colunas sobre `orders` | ~185 ms |
| `ANALYZE` no banco inteiro | ~90 ms |

Duas consequências práticas. Primeiro: **o que você faz por linha do laço mais
externo domina tudo.** Uma subconsulta correlacionada com índice não é uma
tragédia, mas ela paga custo fixo de VDBE por linha e some quando a mesma
informação vem de uma junção agregada de uma vez. Segundo: **construir um índice
custa cerca de oito varreduras da tabela.** Ele só se paga se o que economiza,
somado nas quatro janelas do lote, superar isso.

## Funções sobre a coluna no `WHERE`

```sql
WHERE upper(o.status) = 'DELIVERED'                    -- não usa índice
  AND strftime('%Y-%m-%d', o.order_date) >= :d0        -- não usa índice
```

Um índice em `orders(status, order_date)` é inútil aqui: o planejador só casa o
índice com a coluna crua. E, mesmo sem índice nenhum, a chamada de função por
linha custa — são 60.000 linhas, duas funções cada. Comparar a coluna
diretamente com o parâmetro é o mesmo filtro e nem precisa de índice para ficar
mais barato.

Isso vale igual em Postgres, com o agravante de lá existirem índices sobre
expressão — que resolvem o problema errado. Prefira o predicado sargável.

## Índice: onde a conta fecha e onde não fecha

O regime `frio` cronometra `setup.sql` junto com as quatro janelas do lote; o
`quente` e o `larga` colhem só o benefício. A média geométrica dos três é o
score, então um índice se paga quando o ganho nos dois regimes quentes supera o
custo no frio. Um índice a mais que não é usado por nenhuma consulta é custo
puro e aparece inteiro.

Três coisas que este banco ensina e que não são óbvias:

**Índice cobrindo vale mais aqui do que em uma tabela estreita.** `orders` tem
doze colunas e a consulta usa quatro. Um índice que contenha as quatro responde
sem tocar nas páginas de dados — troca 44 MB de leitura por menos de 3 MB.

**A ordem que o índice impõe às linhas se propaga.** Se o resto da consulta
agrupa por algo que a varredura da tabela já entregava ordenado, e o índice
entrega em outra ordem, o SQLite passa a precisar de um `USE TEMP B-TREE FOR
GROUP BY` que antes não existia. O índice acelera a leitura e paga uma
ordenação nova; o saldo pode ser negativo. É por isso que o índice "óbvio" nem
sempre é o que ganha, e por isso que vale olhar o plano depois de criá-lo, não
só antes.

**Índice parcial existe.** `CREATE INDEX ... WHERE status = 'delivered'` indexa
só o subconjunto que a consulta usa: menos linhas para ordenar na construção,
menos páginas para percorrer na leitura. O SQLite só o usa quando consegue provar
que o `WHERE` da consulta implica o do índice — com um literal, consegue.

## Correlacionada, junção e o nível certo de agregação

O padrão

```sql
SUM((SELECT COALESCE(SUM(i.qty * i.unit_cents), 0)
     FROM order_items i WHERE i.order_id = o.order_id))
```

roda uma busca indexada por pedido da janela. A alternativa é agregar
`order_items` de uma vez e juntar o resultado. Duas armadilhas nessa travessia:

- **Agregar a tabela inteira.** `SELECT order_id, SUM(...) FROM order_items GROUP
  BY order_id` processa 720 mil linhas para usar 60 mil. Restrinja a agregação à
  janela — pela junção com os pedidos filtrados, não depois.
- **Juntar `refunds` no nível errado.** Um pedido tem no máximo um estorno, mas
  tem vários itens. Junte `refunds` no nível do pedido; no nível do item o
  estorno é somado uma vez por item.

## `ANALYZE`

Grava estatísticas em `sqlite_stat1` e muda as escolhas do planejador. Custa
~90 ms de `setup.sql` e neste alvo raramente devolve isso — mas quando o plano
está escolhendo a tabela errada para dirigir a junção, é a ferramenta certa.
`ANALYZE orders` analisa uma tabela só e custa menos. Meça; não presuma.

## O que não fazer

- Materializar o resultado numa tabela em `setup.sql`. O gate recusa
  `CREATE TABLE` pelo nome: guardar a resposta faria o número subir sem que
  consulta nenhuma tivesse ficado melhor.
- Embutir as datas ou o `:top_n` na consulta. O gate roda quatro janelas
  diferentes.
- Criar índice "por precaução". Cada um custa no `frio` e só volta se alguma
  consulta o usar. Confira no plano que ele foi usado.
- `PRAGMA cache_size`, `mmap_size` e afins: valem só para a conexão que os
  executou, e a consulta roda em outra. O avaliador recusa.

## Medindo à mão

```bash
python3 targets/sql_agg/eval.py --workdir work    # os três regimes, como o harness mede
sqlite3 data/perf_shop.sqlite ".timer on" "..."   # uma consulta isolada
```

Para experimentar índice sem sujar nada, copie o banco antes — o avaliador faz
exatamente isso, e o arquivo congelado tem checksum no `dataset.lock.json`.
