-- q6 cesta media por segmento de cliente -- x_0.
--
-- CORRETA e deliberadamente ruim: a juncao com `customers` compara as duas
-- chaves convertidas para texto, e uma funcao sobre a coluna de juncao impede
-- o uso da chave primaria.
WITH ped AS (
    SELECT o.order_id  AS order_id,
           c.segment   AS segment
    FROM orders o
    JOIN customers c ON CAST(c.customer_id AS TEXT) = CAST(o.customer_id AS TEXT)
    WHERE o.status = 'delivered'
      AND o.order_date >= :d0
      AND o.order_date <  :d1
)
SELECT p.segment                                       AS segment,
       COUNT(DISTINCT p.order_id)                      AS n_pedidos,
       COALESCE(SUM(i.qty), 0)                         AS n_itens,
       COALESCE(SUM(i.qty * i.unit_cents), 0)          AS bruto_cents,
       ROUND(1.0 * COALESCE(SUM(i.qty), 0) / COUNT(DISTINCT p.order_id), 3) AS itens_por_pedido
FROM ped p
LEFT JOIN order_items i ON i.order_id = p.order_id
GROUP BY p.segment
ORDER BY p.segment
