# Como o SQLite escolhe um plano, e o que cada coisa custa neste banco

Isto e o dominio: a mecanica do planejador e o mapa de custo medido deste banco.
**Nao ha aqui nenhuma afirmacao sobre quais das oito consultas estao ruins nem
sobre o que fazer com elas.** Diagnosticar cada uma e o problema.

## O banco medido

| tabela | linhas | |
|---|---:|---|
| `orders` | 120 000 | doze colunas, linha larga |
| `order_items` | 353 773 | |
| `customers` | 3 000 | |
| `refunds` | 6 150 | um por pedido, no maximo |
| `products` | 700 | |

38,6 MB congelados, dois anos de `order_date` (2023-01-01 a 2024-12-31).
Varredura completa de `orders`: **12 ms**. De `order_items`: **17 ms**. Esses
sao os pisos: nenhum plano que precise olhar a tabela inteira fica abaixo disso,
e um plano que leve muito mais que isso esta olhando as linhas mais de uma vez.

## Ler o plano

```sql
EXPLAIN QUERY PLAN <a consulta>;
```

O que voce quer ver nas linhas:

- `SCAN orders` — varredura completa. Nem sempre e ruim: para um predicado que
  casa metade da tabela, varrer e mais barato que percorrer indice.
- `SEARCH orders USING INDEX ix (...)` — o indice foi usado, e os `(...)`
  dizem **quais colunas dele** entraram no predicado. Um indice de tres colunas
  usado so pela primeira nao esta rendendo o que custou.
- `USING COVERING INDEX` — o melhor caso: as colunas pedidas estao todas no
  indice e a tabela nao chegou a ser aberta.
- `USE TEMP B-TREE FOR ORDER BY` / `FOR GROUP BY` — o resultado precisou ser
  ordenado num passo a parte.
- `CORRELATED SCALAR SUBQUERY` — a subconsulta e reavaliada **por linha** da
  consulta externa.
- `MATERIALIZE` / `CO-ROUTINE` — como a CTE foi resolvida. `MATERIALIZE` calcula
  uma vez e guarda; `CO-ROUTINE` alimenta o consumidor sob demanda. Referenciar
  uma CTE em contexto correlacionado costuma faze-la ser **recalculada**, e a
  diferenca entre as duas coisas e de ordens de grandeza.

`EXPLAIN QUERY PLAN` custa microssegundos e nao aparece no relogio. Use antes de
mudar qualquer coisa: e mais rapido que medir e diz *por que*.

## Quando um indice pode ser usado

Um indice sobre uma coluna so serve ao predicado se o predicado comparar **a
coluna**, nao uma expressao sobre ela. `f(coluna) = x` e opaco para o
planejador: ele nao sabe inverter `f`. Isso vale para conversao de tipo, para
funcao de data, para concatenacao e para `CAST`, e vale tanto no `WHERE` quanto
no `ON` de uma juncao.

Consequencia pratica que custa tempo de quem nao repara: **criar um indice sobre
uma coluna que a consulta embrulha em funcao nao acelera nada.** O indice e
construido, ocupa espaco, e o plano continua o mesmo. O custo aparece; o
beneficio nao.

O SQLite tambem constroi **indices automaticos transitorios** para juncoes e
subconsultas correlacionadas quando acha que compensa. Eles nao aparecem no
esquema, sao refeitos a cada execucao, e escondem parte do custo de um plano
ruim — o que faz `SEARCH ... USING AUTOMATIC COVERING INDEX` no plano ser um
sinal de que ha um indice permanente faltando ali.

## Indices parciais

`CREATE INDEX ... WHERE <cond>` indexa so as linhas que casam `<cond>`. E menor
e mais barato de construir. A restricao e que o planejador so o usa quando
consegue **provar** que o `WHERE` da consulta implica o `<cond>` do indice.

Isso tem uma consequencia forte aqui: as janelas chegam como **parametros
nomeados** (`:d0`, `:d1`), e o planejador nao sabe o valor deles na hora de
escolher o plano. Um indice parcial condicionado a datas literais nao pode ser
provado aplicavel a `order_date >= :d0` e nao sera usado — so custa. Um indice
parcial condicionado a uma coluna que a consulta filtra por igualdade literal
(`status = 'delivered'`, por exemplo) e provavel e sera usado.

## ANALYZE

Sem `ANALYZE`, o planejador usa heuristicas de cardinalidade — ele **chuta**
quantas linhas cada caminho devolve. Com `ANALYZE`, ele le a tabela
`sqlite_stat1` e decide com numero.

Isso importa mais do que parece num banco com indices: a escolha entre varrer e
percorrer indice depende inteiramente da seletividade estimada, e um chute ruim
faz o planejador preferir o indice justamente onde varrer seria melhor. **Um
indice sem `ANALYZE` pode deixar a consulta mais lenta do que ela era sem indice
nenhum.** Nao e teoria: mede-se em um passo.

`ANALYZE` custa 58 ms neste banco e vale para o banco inteiro.

## O preco de construir, medido

O regime `frio` cronometra `setup.sql` junto com o lote. Estes sao os custos
nesta maquina, medianos de tres construcoes sobre o banco recem-copiado:

| indice | constroi em | banco passa a |
|---|---:|---:|
| `ANALYZE` | 58 ms | 38,6 MB |
| `orders(status, order_date, customer_id)` | 152 ms | 42,4 MB |
| ... o mesmo, `WHERE status = 'delivered'` | 105 ms | 40,8 MB |
| `orders(customer_id, status, order_date)` | 131 ms | 42,4 MB |
| `orders(order_date, status)` | 126 ms | 42,0 MB |
| `orders(channel, order_date) WHERE status='delivered'` | 97 ms | 40,3 MB |
| `order_items(sku)` | 207 ms | 44,6 MB |
| `order_items(sku, order_id, qty, unit_cents)` | 274 ms | 47,7 MB |

Compare com o lote inteiro do seed, que roda em ~850 ms. Dois indices de
`order_items` custam metade de um fechamento; seis indices custam quase um
fechamento completo, todo trimestre, so para construir.

## As tres seletividades

Os tres regimes nao sao o mesmo benchmark medido tres vezes — sao tres
seletividades, e um indice se comporta diferente em cada uma:

| regime | o que roda | quanto da tabela casa o predicado |
|---|---|---|
| `frio` | `setup.sql` + o lote trimestral, banco virgem | ~12% |
| `quente` | o lote trimestral, banco ja preparado | ~12% |
| `estreito` | o lote quinzenal, canal e pais raros | menos de 1% |

Em 12%, percorrer indice e varrer custam a mesma ordem de grandeza e a escolha
depende de detalhes. Abaixo de 1%, o indice ganha de longe. Construir, em
compensacao, so aparece no `frio`. O numero maximizado e a media geometrica dos
tres: uma mudanca que ganha muito num regime e perde em outro perde para uma que
melhora os tres modestamente.
