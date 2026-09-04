-- q1 receita mensal por cliente -- x_0.
--
-- CORRETA e deliberadamente ruim: os dois predicados do WHERE estao embrulhados
-- em funcao, entao nenhum indice sobre `orders` pode ser usado por eles.
WITH bruto AS (
    SELECT o.order_id       AS order_id,
           o.customer_id    AS customer_id,
           substr(o.order_date, 1, 7) AS mes,
           COALESCE(SUM(i.qty * i.unit_cents), 0) AS bruto
    FROM orders o
    LEFT JOIN order_items i ON i.order_id = o.order_id
    WHERE upper(o.status) = 'DELIVERED'
      AND strftime('%Y-%m-%d', o.order_date) >= :d0
      AND strftime('%Y-%m-%d', o.order_date) <  :d1
    GROUP BY o.order_id
)
SELECT b.mes                                                AS mes,
       b.customer_id                                        AS customer_id,
       COUNT(*)                                             AS n_pedidos,
       SUM(b.bruto)                                         AS bruto_cents,
       SUM(COALESCE(r.amount_cents, 0))                     AS estorno_cents,
       SUM(b.bruto) - SUM(COALESCE(r.amount_cents, 0))      AS liquido_cents
FROM bruto b
LEFT JOIN refunds r ON r.order_id = b.order_id
GROUP BY b.mes, b.customer_id
ORDER BY b.mes, liquido_cents DESC, b.customer_id
