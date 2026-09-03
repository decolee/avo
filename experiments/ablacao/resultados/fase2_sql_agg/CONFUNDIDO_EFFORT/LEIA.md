# Braço `greedy` medido com esforço diferente do `full`

Estas onze sementes rodaram com `--effort medium`. As do `full`, no mesmo
experimento, rodaram com `--effort xhigh`. Comparar as duas mede esforço, não
arquitetura, e `docs/ABLATION_PROTOCOL.md` §4 exige orçamento igualado entre
braços — inclusive esse.

**A causa.** O comando que cria o run no `runner.py` nunca passou `--effort`,
então o harness aplicou o default dele (`xhigh`, `config.py:196`). O parâmetro
`effort` de `roda_um` existia na assinatura, era passado pelo `main`, e era
**código morto** para o braço caro. O `greedy`, que monta o próprio argv, passava
`medium` corretamente. Os dois lados estavam certos isoladamente e errados juntos.

Achado ao investigar outra coisa: uma semente do `full` falhou com `claude exited
1`, e o `argv` no log do passo mostrava `--effort xhigh` onde eu esperava
`medium`.

**Quanto tempo durou.** Desde o primeiro run não supervisionado deste
laboratório. Vale para a ablação do `csv_normalize` e para o controle honesto:
nos dois, o `full` teve mais esforço que o `greedy`, e o desequilíbrio favorece
o `full`.

**O conserto.** `runner.py` passa `--effort` explicitamente, e `programa.py`
passa `xhigh` em todas as fases. Padronizado em `xhigh`, não em `medium`, por
duas razões: é o default do harness — a configuração que o AVO "pretende" — e
refazer o braço barato custa ~US$ 66 contra ~US$ 440 de refazer o caro.

**O que os números diziam.** Em `medium`, `greedy_nat` mediu 4,574 ± 0,158 (n=11).
O braço vai ser refeito em `xhigh` e os dois valores ficam publicados: a
diferença entre eles é uma medida direta do que o esforço compra numa sessão
única, que é informação que este laboratório não tinha.
