-- q7 primeira compra entregue de cada cliente na janela -- x_0.
--
-- CORRETA e deliberadamente ruim: o "primeiro" e decidido por DUAS subconsultas
-- correlacionadas contra a propria CTE, avaliadas linha a linha. O
-- `MATERIALIZED` mantem o seed na escala de um relatorio: sem ele a CTE seria
-- reconstruida a cada linha e a consulta levaria minutos.
WITH ped AS MATERIALIZED (
    SELECT o.order_id    AS order_id,
           o.customer_id AS customer_id,
           o.order_date  AS order_date
    FROM orders o
    WHERE o.status = 'delivered'
      AND o.order_date >= :d0
      AND o.order_date <  :d1
)
SELECT p.customer_id AS customer_id,
       p.order_id    AS order_id,
       p.order_date  AS order_date,
       COALESCE((SELECT SUM(i.qty * i.unit_cents) FROM order_items i
                 WHERE i.order_id = p.order_id), 0) AS bruto_cents
FROM ped p
WHERE p.order_date = (SELECT MIN(q.order_date) FROM ped q
                       WHERE q.customer_id = p.customer_id)
  AND p.order_id   = (SELECT MIN(q.order_id) FROM ped q
                       WHERE q.customer_id = p.customer_id
                         AND q.order_date = p.order_date)
ORDER BY p.customer_id
