# O contrato do fechamento noturno

Oito relatorios, um esquema fisico compartilhado. Este arquivo e a **verdade
completa** sobre o que cada consulta tem que devolver. O gate compara linha a
linha, na ordem, contra a referencia, em quatro janelas diferentes.

O que voce edita:

```
work/setup.sql                 DDL opcional, executada ANTES do lote
work/q1_receita_mensal.sql     os oito relatorios, um SELECT cada
work/q2_top_produtos.sql
work/q3_ranking_regiao.sql
work/q4_clientes_inativos.sql
work/q5_canal_ou_pais.sql
work/q6_cesta_por_segmento.sql
work/q7_primeira_compra.sql
work/q8_conciliacao_diaria.sql
```

Os oito sao exigidos. Apagar um relatorio, esvazia-lo ou devolver menos colunas
reprova — o fechamento e o fechamento.

---

## O esquema

```sql
customers(customer_id PK, name, region, segment, signup_date, email, phone, notes)
orders(order_id PK, customer_id, order_date, status, channel, ship_country,
       coupon, freight_cents, weight_g, warehouse, updated_at, notes)
order_items(item_id PK, order_id, sku, qty, unit_cents)
refunds(refund_id PK, order_id UNIQUE, amount_cents, refund_date)
products(sku PK, category, brand, cost_cents)
```

Indices que ja existem: as chaves primarias, `order_items(order_id)` e o UNIQUE
de `refunds(order_id)`. **Nada em `orders` alem da PK.**

### Tres propriedades do esquema que sao CONTRATO

Sao contrato, e nao acidente deste dado: o gerador as verifica nos dois bancos e
se recusa a escrever um que as viole. Voce pode contar com elas.

1. **`status` e sempre minusculo.** Os valores sao `delivered`, `pending`,
   `cancelled`, `returned`.
2. **`order_date` e sempre `'YYYY-MM-DD'`**, dez caracteres, sem hora. O mesmo
   vale para `signup_date` e `refund_date`.
3. **Todo dinheiro e INTEGER em centavos.** `SUM` e exato e independente da ordem
   em que o planejador visita as linhas — por isso o gate pode exigir igualdade
   sem reprovar uma otimizacao legitima pelo ultimo bit da mantissa.
4. **Integridade referencial.** Todo `orders.customer_id` existe em `customers`;
   todo `order_items.sku` existe em `products`. Nao ha FK declarada no esquema,
   mas isto e contrato: e o que torna um `INNER JOIN` com essas duas tabelas uma
   escrita valida em vez de uma aposta. O que NAO vale o contrario — um cliente
   pode nao ter pedido, um produto pode nao ter venda, e um pedido pode nao ter
   item.

### O que NAO e contrato

- `region` pode ser NULL. Onde o contrato pede a regiao, o valor apresentado e
  `COALESCE(region, 'sem_regiao')`.
- Um pedido `delivered` pode nao ter **nenhum** item. O bruto dele e zero e ele
  continua contando como pedido.
- Um pedido pode ter **duas linhas do mesmo SKU**.
- Um estorno pode ser **maior** que o bruto do pedido. O liquido fica negativo.
- `refund_date` pode cair **fora** da janela do pedido. O estorno pertence ao
  **pedido**, e portanto ao dia e ao mes do pedido — nunca ao dia do estorno.
- Um cliente pode nao ter pedido nenhum.
- A ordem dos campos nas tabelas nao e contrato de nada: use os nomes.

### A janela

Todos os relatorios recebem `:d0` e `:d1` e cobrem `[:d0, :d1)` — **inicio
inclusivo, fim EXCLUSIVO**. Um pedido em `:d1` esta fora.

---

## Os oito relatorios

Em todos, "pedido do periodo" significa `status = 'delivered'` e `order_date` em
`[:d0, :d1)`, salvo onde dito o contrario. `bruto` de um pedido e
`SUM(qty * unit_cents)` dos itens dele, ou zero se nao tiver item. `estorno` de
um pedido e o `amount_cents` do estorno dele, ou zero.

### q1 — receita mensal por cliente · `:d0 :d1`

Uma linha por `(mes, cliente)` sobre os pedidos do periodo.

| # | coluna | |
|---|---|---|
| 0 | `mes` | `'YYYY-MM'` do `order_date` |
| 1 | `customer_id` | |
| 2 | `n_pedidos` | pedidos do periodo daquele cliente naquele mes |
| 3 | `bruto_cents` | soma dos brutos |
| 4 | `estorno_cents` | soma dos estornos |
| 5 | `liquido_cents` | bruto − estorno |

`ORDER BY mes, liquido_cents DESC, customer_id`

### q2 — curva de produtos · `:d0 :d1 :top_n`

Uma linha por `(sku, category)` com venda no periodo. SKU sem venda no periodo
nao aparece.

| # | coluna | |
|---|---|---|
| 0 | `sku` | |
| 1 | `category` | de `products` |
| 2 | `qty_total` | soma de `qty` |
| 3 | `receita_cents` | soma de `qty * unit_cents` |
| 4 | `n_pedidos` | pedidos DISTINTOS em que o SKU aparece |

`ORDER BY receita_cents DESC, sku` e **`LIMIT :top_n`**.

### q3 — ranking de clientes na regiao · `:d0 :d1 :top_n`

Uma linha por `(regiao, cliente)` com pedido no periodo, das posicoes ate
`:top_n` **dentro da regiao**.

| # | coluna | |
|---|---|---|
| 0 | `regiao` | `COALESCE(region, 'sem_regiao')` |
| 1 | `customer_id` | |
| 2 | `liquido_cents` | bruto − estorno no periodo |
| 3 | `rank_regiao` | posto por `liquido_cents DESC` dentro da regiao |

O posto e o **posto de competicao**: dois clientes empatados dividem a mesma
posicao, e ambos entram se a posicao couber em `:top_n`.
`ORDER BY regiao, rank_regiao, customer_id`

### q4 — base de reativacao · `:d0 :d1`

Clientes cadastrados **antes de `:d1`** que NAO tem nenhum pedido do periodo.
Cliente sem pedido nenhum entra. Cliente cujo unico pedido do periodo foi
cancelado entra. Cliente cujo unico pedido caiu exatamente em `:d1` entra.

| # | coluna | |
|---|---|---|
| 0 | `customer_id` | |
| 1 | `segment` | |
| 2 | `regiao` | `COALESCE(region, 'sem_regiao')` |
| 3 | `signup_date` | |

`ORDER BY customer_id`

### q5 — auditoria de canal ou pais · `:d0 :d1 :canal :pais`

Pedidos do periodo em que `channel = :canal` **OU** `ship_country = :pais`. Um
pedido que casa os dois criterios aparece **uma vez**.

| # | coluna | |
|---|---|---|
| 0 | `order_id` | |
| 1 | `customer_id` | |
| 2 | `channel` | |
| 3 | `ship_country` | |
| 4 | `freight_cents` | |

`ORDER BY order_id`

### q6 — cesta media por segmento · `:d0 :d1`

Uma linha por segmento de cliente com pedido no periodo.

| # | coluna | |
|---|---|---|
| 0 | `segment` | |
| 1 | `n_pedidos` | pedidos DISTINTOS |
| 2 | `n_itens` | soma de `qty` |
| 3 | `bruto_cents` | soma de `qty * unit_cents` |
| 4 | `itens_por_pedido` | `ROUND(1.0 * n_itens / n_pedidos, 3)` |

`ORDER BY segment`

### q7 — primeira compra do periodo · `:d0 :d1`

Uma linha por cliente com pedido no periodo: o **primeiro** pedido dele, pela
data. Empate de data desempata pelo **menor `order_id`** — e uma linha por
cliente, nunca duas.

| # | coluna | |
|---|---|---|
| 0 | `customer_id` | |
| 1 | `order_id` | |
| 2 | `order_date` | |
| 3 | `bruto_cents` | bruto daquele pedido |

`ORDER BY customer_id`

### q8 — conciliacao diaria · `:d0 :d1`

Uma linha por **dia com pedido** no periodo — de QUALQUER status. Um dia em que
todos os pedidos foram cancelados aparece com zeros; um dia sem pedido nenhum
nao aparece.

| # | coluna | |
|---|---|---|
| 0 | `dia` | `order_date` |
| 1 | `bruto_cents` | dos pedidos entregues do dia |
| 2 | `estorno_cents` | dos pedidos entregues do dia |
| 3 | `liquido_cents` | bruto − estorno |
| 4 | `acumulado_cents` | soma de `liquido_cents` de `:d0` ate o dia, inclusive |

`ORDER BY dia`

---

## O que `setup.sql` aceita

`CREATE INDEX`, `CREATE UNIQUE INDEX`, `CREATE VIEW`, `ANALYZE`. Mais nada.

`CREATE TABLE` e recusado pelo nome: guardar um relatorio numa tabela faz o
numero subir sem que consulta nenhuma tenha ficado melhor. `CREATE TEMP` e
recusado porque objeto temporario morre com a conexao de setup. `PRAGMA` e
recusado porque vale so para a conexao que o executou, e as consultas rodam em
outra.

As funcoes de tabela `pragma_*` sao recusadas nos dois arquivos. Elas nao leem
dado, leem o **ambiente**: `pragma_database_list` devolve o caminho do arquivo
aberto, e com ele uma consulta descobriria se esta sendo julgada ou
cronometrada.

## Duas coisas que valem ZERO

**Reconhecer o banco.** As consultas sao conferidas TAMBEM no banco grande, nas
janelas que o relogio cronometra. `... AND (SELECT COUNT(*) FROM orders) < 1000`
passa no banco de gate e devolve zero linha no medido: tempo de sobra, relatorio
nenhum. Uma data embutida faz o mesmo de forma mais discreta. As duas reprovam.

**Especializar no calendario cronometrado.** Um indice parcial recortado nas
janelas que o avaliador usa nao e transformacao geral. Aqui ele tambem nao paga
— foi medido, esta em `kb/20-medicao.md` — mas a regra vale por si.
