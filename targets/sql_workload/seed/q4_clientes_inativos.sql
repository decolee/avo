-- q4 clientes sem compra entregue na janela -- x_0.
--
-- CORRETA e deliberadamente ruim: a anti-juncao esta escrita como um COUNT(*)
-- correlacionado, avaliado uma vez por cliente. O `MATERIALIZED` esta aqui de
-- proposito: sem ele a CTE seria reavaliada a cada cliente e a consulta sairia
-- da escala de um relatorio noturno -- o seed e ingenuo, nao catastrofico.
WITH ped AS MATERIALIZED (
    SELECT o.customer_id AS customer_id
    FROM orders o
    WHERE o.status = 'delivered'
      AND o.order_date >= :d0
      AND o.order_date <  :d1
)
SELECT c.customer_id                     AS customer_id,
       c.segment                         AS segment,
       COALESCE(c.region, 'sem_regiao')  AS regiao,
       c.signup_date                     AS signup_date
FROM customers c
WHERE c.signup_date < :d1
  AND (SELECT COUNT(*) FROM ped p WHERE p.customer_id = c.customer_id) = 0
ORDER BY c.customer_id
