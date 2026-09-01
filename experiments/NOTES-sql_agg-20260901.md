# Working notes

Scratch space that survives across variation steps. The framework never writes
here — it is yours.

Worth keeping: what you tried and what it measured, dead ends (so a later step
does not re-walk them), and any structure of the problem you had to work out.


## Beco medido — mais dois índices (a tensão que o alvo existe para criar)

Adicionei `order_items(order_id, qty, unit_cents)` e `refunds(order_id, amount_cents)`
por cima do índice de `orders`.

| regime | com 1 índice | com 3 índices | efeito |
|---|---|---|---|
| `quente` | 5,18 | 6,32 | **+22%** |
| `larga` | 4,88 | 5,84 | **+20%** |
| `frio` | 2,99 | **1,30** | **−56%** |
| geomean | **4,21** | 3,64 | −13,6% |

As consultas ficaram genuinamente mais rápidas — e o score caiu.

Construir os dois índices custa ~430 ms, e o regime `frio` cronometra o
`setup.sql` junto com o lote de quatro consultas. O ganho por consulta não paga
a construção dentro de uma única avaliação.

**Não é um defeito do score, é o ponto dele.** Um alvo que medisse só o
`quente` ensinaria "crie todo índice imaginável", que é errado em qualquer banco
de produção. A média geométrica dos dois regimes força a pergunta certa: este
índice se paga no horizonte em que ele vai ser usado?

**Quando isto deixaria de ser beco:** se o lote do `frio` fosse maior (mais
janelas por avaliação), a construção se amortizaria e os três índices passariam
a ganhar. O `frio` já mede um lote de quatro janelas justamente para que
*algum* índice se pague — o de `orders` se paga, estes dois não.

Não re-tentar como estão. Vale testar índice parcial (só `status='delivered'`),
que é mais barato de construir.
