-- q2 top produtos por receita -- x_0.
--
-- CORRETA e deliberadamente ruim: a CTE agrega os itens do periodo INTEIRO
-- antes de qualquer filtro de janela. Agregar bloqueia o empurrao do predicado.
WITH vendas AS (
    SELECT i.order_id             AS order_id,
           i.sku                  AS sku,
           SUM(i.qty)             AS qty,
           SUM(i.qty * i.unit_cents) AS receita
    FROM order_items i
    GROUP BY i.order_id, i.sku
)
SELECT v.sku                      AS sku,
       p.category                 AS category,
       SUM(v.qty)                 AS qty_total,
       SUM(v.receita)             AS receita_cents,
       COUNT(DISTINCT v.order_id) AS n_pedidos
FROM vendas v
JOIN orders   o ON o.order_id = v.order_id
JOIN products p ON p.sku = v.sku
WHERE o.status = 'delivered'
  AND o.order_date >= :d0
  AND o.order_date <  :d1
GROUP BY v.sku, p.category
ORDER BY receita_cents DESC, sku
LIMIT :top_n
