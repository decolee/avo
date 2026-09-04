-- q3 ranking de clientes dentro da regiao -- x_0.
--
-- CORRETA e deliberadamente ruim: o posto e calculado por auto-juncao
-- correlacionada com a propria CTE, uma vez para exibir e outra para filtrar.
WITH liq AS (
    SELECT COALESCE(c.region, 'sem_regiao') AS regiao,
           o.customer_id                    AS customer_id,
           SUM(COALESCE((SELECT SUM(i.qty * i.unit_cents) FROM order_items i
                         WHERE i.order_id = o.order_id), 0))
             - SUM(COALESCE((SELECT r.amount_cents FROM refunds r
                             WHERE r.order_id = o.order_id), 0)) AS liquido_cents
    FROM orders o
    JOIN customers c ON c.customer_id = o.customer_id
    WHERE o.status = 'delivered'
      AND o.order_date >= :d0
      AND o.order_date <  :d1
    GROUP BY regiao, o.customer_id
)
SELECT g.regiao          AS regiao,
       g.customer_id     AS customer_id,
       g.liquido_cents   AS liquido_cents,
       (SELECT COUNT(*) + 1 FROM liq h
         WHERE h.regiao = g.regiao AND h.liquido_cents > g.liquido_cents) AS rank_regiao
FROM liq g
WHERE (SELECT COUNT(*) + 1 FROM liq h
        WHERE h.regiao = g.regiao AND h.liquido_cents > g.liquido_cents) <= :top_n
ORDER BY g.regiao, rank_regiao, g.customer_id
