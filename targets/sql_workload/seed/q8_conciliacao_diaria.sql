-- q8 conciliacao diaria com acumulado -- x_0.
--
-- CORRETA e deliberadamente ruim: cada dia paga a sua propria varredura do
-- periodo, e o acumulado paga mais uma por linha. Os `MATERIALIZED` mantem o
-- seed na escala de um relatorio noturno -- sem eles a varredura seria da
-- tabela inteira, uma vez por dia, e a consulta levaria dezenas de segundos.
WITH ped AS MATERIALIZED (
    SELECT o.order_id   AS order_id,
           o.order_date AS order_date,
           o.status     AS status
    FROM orders o
    WHERE o.order_date >= :d0
      AND o.order_date <  :d1
),
dias AS (
    SELECT DISTINCT p.order_date AS dia FROM ped p
),
diario AS MATERIALIZED (
    SELECT d.dia AS dia,
           COALESCE((SELECT SUM(i.qty * i.unit_cents)
                     FROM ped p JOIN order_items i ON i.order_id = p.order_id
                     WHERE p.order_date = d.dia AND p.status = 'delivered'), 0) AS bruto_cents,
           COALESCE((SELECT SUM(r.amount_cents)
                     FROM ped p JOIN refunds r ON r.order_id = p.order_id
                     WHERE p.order_date = d.dia AND p.status = 'delivered'), 0) AS estorno_cents
    FROM dias d
)
SELECT a.dia            AS dia,
       a.bruto_cents    AS bruto_cents,
       a.estorno_cents  AS estorno_cents,
       a.bruto_cents - a.estorno_cents AS liquido_cents,
       (SELECT SUM(b.bruto_cents - b.estorno_cents) FROM diario b
         WHERE b.dia <= a.dia) AS acumulado_cents
FROM diario a
ORDER BY a.dia
