-- Receita por cliente e mes, com ranking dentro do mes -- x_0.
--
-- CONTRATO (a verdade completa esta em kb/00-contrato.md):
--
--   Parametros nomeados, ligados pelo avaliador a cada execucao:
--     :d0      data inicial INCLUSIVA  'YYYY-MM-DD'
--     :d1      data final   EXCLUSIVA  'YYYY-MM-DD'
--     :top_n   posto maximo mantido em cada mes
--
--   Dez colunas, nesta ordem (o nome delas nao importa, a ordem sim):
--     mes TEXT 'YYYY-MM' | customer_id | region | n_pedidos | n_estornos
--     bruto_cents | estorno_cents | liquido_cents | pct_estorno | rank_mes
--
--   Uma linha por (mes, cliente) entre os pedidos com status 'delivered' e
--   order_date em [:d0, :d1). ORDER BY mes DESC, liquido_cents DESC,
--   customer_id -- mes mais recente primeiro. A ordem faz parte do contrato
--   e o gate a compara linha a linha.
--
-- Esta consulta esta CORRETA e e deliberadamente ruim. Ela e o que sai de
-- traduzir o contrato para SQL sem pensar no plano: uma subconsulta
-- correlacionada por valor agregado, funcao aplicada sobre a coluna no WHERE,
-- o cliente juntado no meio da agregacao e o ranking calculado por auto-juncao
-- com a propria CTE, uma vez para exibir e outra para filtrar.
--
-- Nada em setup.sql. Nenhum indice novo.

WITH agg AS (
    SELECT
        substr(o.order_date, 1, 7) AS mes,
        o.customer_id AS customer_id,
        c.region AS region,
        COUNT(DISTINCT o.order_id) AS n_pedidos,
        SUM(CASE WHEN (SELECT COUNT(*) FROM refunds r WHERE r.order_id = o.order_id) > 0
                 THEN 1 ELSE 0 END) AS n_estornos,
        SUM((SELECT COALESCE(SUM(i.qty * i.unit_cents), 0)
             FROM order_items i WHERE i.order_id = o.order_id)) AS bruto_cents,
        SUM((SELECT COALESCE(SUM(r.amount_cents), 0)
             FROM refunds r WHERE r.order_id = o.order_id)) AS estorno_cents,
        SUM((SELECT COALESCE(SUM(i.qty * i.unit_cents), 0)
             FROM order_items i WHERE i.order_id = o.order_id))
          - SUM((SELECT COALESCE(SUM(r.amount_cents), 0)
             FROM refunds r WHERE r.order_id = o.order_id)) AS liquido_cents
    FROM orders o
    JOIN customers c ON c.customer_id = o.customer_id
    WHERE upper(o.status) = 'DELIVERED'
      AND strftime('%Y-%m-%d', o.order_date) >= :d0
      AND strftime('%Y-%m-%d', o.order_date) <  :d1
    GROUP BY substr(o.order_date, 1, 7), o.customer_id, c.region
)
SELECT
    g.mes,
    g.customer_id,
    g.region,
    g.n_pedidos,
    g.n_estornos,
    g.bruto_cents,
    g.estorno_cents,
    g.liquido_cents,
    CASE WHEN g.bruto_cents > 0
         THEN ROUND(100.0 * g.estorno_cents / g.bruto_cents, 2)
         ELSE 0.0 END AS pct_estorno,
    (SELECT COUNT(*) + 1 FROM agg h
      WHERE h.mes = g.mes AND h.liquido_cents > g.liquido_cents) AS rank_mes
FROM agg g
WHERE (SELECT COUNT(*) + 1 FROM agg h
        WHERE h.mes = g.mes AND h.liquido_cents > g.liquido_cents) <= :top_n
ORDER BY g.mes DESC, g.liquido_cents DESC, g.customer_id
