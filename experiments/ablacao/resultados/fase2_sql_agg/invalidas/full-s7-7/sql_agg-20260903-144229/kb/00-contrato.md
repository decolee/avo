# Contrato da consulta — a verdade sobre o result set

`work/query.sql` é **um** comando SQL: um `SELECT`, podendo abrir com `WITH`.
Nada de DDL, nada de DML, nada de `PRAGMA`, e nada de dois comandos separados
por `;`. A conexão que executa a consulta é aberta em `mode=ro`, então uma
escrita que escapasse da checagem estática morreria no SQLite de qualquer jeito.

## Parâmetros

O avaliador liga três parâmetros nomeados a cada execução:

| parâmetro | tipo | significado |
|---|---|---|
| `:d0` | TEXT `'YYYY-MM-DD'` | início da janela, **inclusivo** |
| `:d1` | TEXT `'YYYY-MM-DD'` | fim da janela, **exclusivo** |
| `:top_n` | INTEGER | posto máximo mantido dentro de cada mês |

A janela é `[:d0, :d1)`. Um pedido com `order_date = :d1` **não** entra. Esse é
o erro de borda mais comum e o banco de gate tem um pedido plantado exatamente
nessa data para pegá-lo.

Usar um parâmetro que não existe é erro de execução. Ignorar um que existe é
pior: o gate roda a consulta com quatro conjuntos de parâmetros diferentes, e
uma consulta com as datas embutidas passa em um e falha nos outros três.

## Esquema

```sql
customers (customer_id INTEGER PRIMARY KEY, name TEXT, region TEXT,
           segment TEXT, signup_date TEXT)                    -- region pode ser NULL

orders    (order_id INTEGER PRIMARY KEY,
           customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
           order_date TEXT,
           status TEXT, channel TEXT, payment_method TEXT, ship_city TEXT,
           ship_state TEXT, ship_zip TEXT, coupon_code TEXT, device TEXT,
           note TEXT)                                         -- doze colunas, larga

order_items (item_id INTEGER PRIMARY KEY, order_id INTEGER,
             product_id INTEGER, qty INTEGER, unit_cents INTEGER)

refunds   (refund_id INTEGER PRIMARY KEY, order_id INTEGER UNIQUE,
           amount_cents INTEGER, refund_date TEXT)
```

Três fatos do esquema que mudam o que é correto escrever:

- **`refunds.order_id` é UNIQUE**: no máximo um estorno por pedido. Juntar
  `refunds` não multiplica linha — desde que a junção aconteça no nível do
  pedido. No nível do **item**, sim: um pedido com quatro itens somaria o
  estorno quatro vezes.
- **Um pedido pode não ter item nenhum.** Existe no banco de gate. `INNER JOIN
  order_items` faz o pedido, e às vezes o cliente inteiro, sumir do relatório.
- **`customers.region` pode ser NULL.** O contrato manda devolver o NULL como
  está; trocá-lo por `''` ou `'sem regiao'` é divergência.
- **`orders.customer_id` é `NOT NULL` e referencia `customers`.** Não existe
  pedido órfão em banco nenhum deste alvo, então buscar a região por junção ou
  por subconsulta correlacionada dá o mesmo result set. O que muda entre as duas
  é o plano, não a resposta — e é por isso que essa escolha é sua.

Índices que já existem: as chaves primárias, `order_items(order_id)` e o índice
implícito de `refunds(order_id) UNIQUE`. **Não existe índice em `orders`.**

## As dez colunas de saída, nesta ordem

| # | coluna | tipo | definição |
|---|---|---|---|
| 0 | `mes` | TEXT `'YYYY-MM'` | mês de `order_date` |
| 1 | `customer_id` | INTEGER | do pedido |
| 2 | `region` | TEXT ou NULL | de `customers`, propagando o NULL |
| 3 | `n_pedidos` | INTEGER | quantos pedidos o grupo tem |
| 4 | `n_estornos` | INTEGER | quantos **pedidos** do grupo têm estorno |
| 5 | `bruto_cents` | INTEGER | `SUM(qty * unit_cents)` dos itens dos pedidos do grupo |
| 6 | `estorno_cents` | INTEGER | soma dos estornos dos pedidos do grupo |
| 7 | `liquido_cents` | INTEGER | `bruto_cents - estorno_cents` |
| 8 | `pct_estorno` | REAL | ver abaixo |
| 9 | `rank_mes` | INTEGER | ver abaixo |

O **nome** das colunas não importa; a **ordem** e o **tipo** importam. Devolver
`bruto_cents` como REAL (por exemplo por multiplicar por `1.0` em algum lugar) é
divergência: `1234` e `1234.0` não são a mesma célula.

## Quais linhas entram

Pedidos com `status = 'delivered'` e `order_date` em `[:d0, :d1)`. Nada mais.
`pending`, `shipped`, `cancelled` e `returned` ficam de fora — inclusive
`returned`, que parece um pedido concluído e não é. Ler o filtro como "não
cancelado" muda o resultado, e o gate tem um cliente com os quatro status no
mesmo mês só para isso.

Um grupo é um par (mês, cliente). Cliente sem pedido na janela não aparece.

## `liquido_cents` pode ser negativo

Estorno maior que a venda acontece, e `liquido_cents` fica negativo. O ranking
tem que aceitar isso sem tratamento especial: nada de `MAX(x, 0)`.

## `pct_estorno` — a única conta com ponto flutuante

```
pct_estorno = CASE WHEN bruto_cents > 0
                   THEN ROUND(100.0 * estorno_cents / bruto_cents, 2)
                   ELSE 0.0 END
```

Duas coisas, e as duas são pegadinhas de verdade:

**O arredondamento é sobre a razão das somas do grupo, uma vez só.** Calcular o
percentual pedido a pedido e tirar a média dá outro número. No banco de gate há
um cliente com um pedido de R$ 1.000,00 com metade estornada e outro de R$ 10,00
sem estorno: a média por pedido dá `25.00`, a razão das somas dá `49.50`. Os dois
são "um percentual de estorno"; só um é o contrato.

**Denominador zero devolve `0.0`, não NULL.** Um pedido sem item com estorno
existe: `bruto_cents = 0` e `estorno_cents > 0`. Em SQL, `x / 0` é NULL, e uma
consulta sem a guarda devolve NULL onde o contrato pede `0.0`.

Todo o resto do dinheiro é `INTEGER` em centavos de propósito. `SUM` sobre
inteiro é exato e não depende da ordem em que o planejador visita as linhas, e é
por isso que o gate pode exigir igualdade byte a byte sem reprovar uma otimização
legítima pelo último bit da mantissa. Não converta para REAL no meio do caminho.

## `rank_mes` — posto dentro do mês

Posto por `liquido_cents` decrescente, **dentro de cada mês**, com **empates
recebendo o mesmo posto**: dois clientes com o mesmo líquido no mesmo mês
recebem o mesmo número, e o posto seguinte pula (1, 2, 2, 4). Essa é a semântica
de `RANK` e não a de `ROW_NUMBER`, que desempataria arbitrariamente, nem a de
`DENSE_RANK`, que não pularia. Como calcular isso é decisão sua — o contrato
manda no número, não na forma.

Só as linhas com `rank_mes <= :top_n` entram no result set. Com empate na
fronteira, um mês pode devolver **mais** de `:top_n` linhas — e um mês com poucos
clientes devolve menos. Quem assume "sempre `:top_n` linhas por mês" erra nos
dois sentidos, e o banco de gate tem um mês com dois clientes e `:top_n = 5`.

O banco de gate tem empate exato de `liquido_cents` dentro de um mês. É a única
coisa que separa `RANK` de `ROW_NUMBER`, e ela está lá por isso.

## Ordenação — faz parte do contrato

```
ORDER BY mes DESC, liquido_cents DESC, customer_id
```

Mês mais recente primeiro. O gate compara linha a linha, na ordem, e um
relatório com as mesmas linhas em outra ordem é outro relatório.

Repare que essa **não** é a ordem que o plano entrega de graça. Calcular o posto
por líquido, de qualquer forma que seja, já deixa as linhas quase arrumadas — em
`(mes, liquido DESC)` **crescente** no mês — então uma consulta sem `ORDER BY`
sai quase certa. "Quase" é zero aqui: o mês vai ao contrário. O `ORDER BY` é
explícito e é seu.

## Como a correção é decidida

Num banco separado (`data/gate_shop.sqlite`), montado linha a linha, nunca no
banco de performance. Ele é consultado com **quatro** conjuntos de parâmetros,
um deles devolvendo zero linhas. O result set precisa bater exatamente: número
de colunas, número de linhas, cada célula, na ordem.

Quando não bate, o avaliador diz qual janela, qual linha, qual coluna, o
esperado e o obtido. Se você recebeu só "N linhas, esperadas M", o problema
quase sempre é um dos três: filtro de data na borda, `LEFT JOIN` virado em
`INNER`, ou o corte por `:top_n` aplicado antes do ranking.

Passado o gate, o avaliador ainda roda a sua consulta nas **cinco janelas que o
relógio cronometra**, agora no banco de performance, e exige o mesmo result set
que a referência produz ali. Isso não é o gate de novo: é a checagem de que o
tempo medido é o tempo de produzir o relatório. Uma consulta que devolve o
relatório certo no banco pequeno e nada no grande — por uma data embutida, por
um predicado sobre o tamanho da tabela, por qualquer coisa que dependa de QUAL
banco está aberto — é rejeitada aqui, com `correct=false`. Pela mesma razão as
funções de tabela `pragma_*` são recusadas na leitura estática: elas leem o
ambiente (o caminho do arquivo), não os dados.

## `setup.sql`

Executado antes da consulta, sobre a mesma cópia do banco, e **cronometrado
junto no regime frio**. Aceita `CREATE INDEX`, `CREATE UNIQUE INDEX`,
`CREATE VIEW` e `ANALYZE`. Recusa `CREATE TABLE` (materializar o resultado não é
otimizar a consulta), objetos temporários (morrem com a conexão de setup),
`PRAGMA` (vale só para a conexão que o executou) e qualquer coisa que altere
dados.
