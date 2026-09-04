-- q5 pedidos por canal OU pais de entrega -- x_0.
--
-- CORRETA e deliberadamente ruim: o `OR` entre duas colunas diferentes impede
-- que um unico indice atenda o predicado.
SELECT o.order_id      AS order_id,
       o.customer_id   AS customer_id,
       o.channel       AS channel,
       o.ship_country  AS ship_country,
       o.freight_cents AS freight_cents
FROM orders o
WHERE o.status = 'delivered'
  AND o.order_date >= :d0
  AND o.order_date <  :d1
  AND (o.channel = :canal OR o.ship_country = :pais)
ORDER BY o.order_id
