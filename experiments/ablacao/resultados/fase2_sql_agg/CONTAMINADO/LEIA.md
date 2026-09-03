# Dados contaminados — dois programas rodaram ao mesmo tempo

Entre 22h22 e 00h20 do dia 2–3, **dois processos do `programa.py` rodaram em
paralelo**. Um `pkill -f "^python3 ..."` com âncora não casou o processo antigo,
e eu presumi que tinha matado. O novo mediu onze sessões de `greedy_nat`
enquanto o antigo executava passos do `full` s1 na mesma máquina.

A prova está no log: às 23h55 o processo antigo imprime `full s1: ... em 5566s`
entre duas linhas do processo novo rodando `greedy_nat`.

**Por que isso invalida.** O `f` deste laboratório é vazão medida em wall-clock.
Dois agentes disputando CPU medem um número que não é o do candidato. É a
contaminação que `ABLATION_PROTOCOL.md` §4 existe para impedir, e a única regra
do protocolo que eu não tinha tornado verificável.

**O que ficou de fora da quarentena:** `greedy_nat` s0 e `full` s0, medidos antes
das 20h24 por um processo único.

**Um segundo defeito, achado junto.** O `full` s1 registrou `primary_seed =
11.073` e ganho `1.00x`. A retomada parcial reusava o run dir e lia o baseline
com `_estado()`, que devolve a ÚLTIMA linha do `scores.jsonl` — num run retomado,
o melhor score já conquistado. O ganho verdadeiro daquela semente era **4,473×**.
Corrigido com `_seed_inicial()`, que lê a versão 0.

**Os consertos.** `programa.trava_exclusiva()` com `flock`, que o kernel libera
quando o processo morre (inclusive por SIGKILL ou reciclagem de container, então
nunca deixa trava órfã); e `_seed_inicial()` no lugar de `_estado()` para o
baseline.

**Nota sobre o que os números mostram.** Sob contaminação o `greedy_nat` mediu
4,60 ± 0,20 (n=11); no piloto limpo, 4,55 ± 0,19 (n=5). Indistinguíveis — o que
sugere que a razão contra o seed da própria semente absorveu a contaminação. Isso
é evidência a favor do normalizador, **não** motivo para manter o dado: o ponto
do protocolo é não depender de "parece que deu certo".
