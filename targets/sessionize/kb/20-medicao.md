# Medição: em que delta acreditar

## Como o número é produzido

Para cada um dos três regimes: uma execução de aquecimento descartada, depois
cinco cronometradas, e a **mediana**. O throughput do regime é `1 / mediana`, e
o score é a média geométrica dos três.

Mediana e não melhor-de-cinco: o melhor-de-N recompensa variância, e a forma
mais barata de melhorá-lo é rodar mais vezes, não ficar mais rápido.

## Quanto de ruído esperar

O avaliador reporta o coeficiente de variação por regime em `notes`:

```
medianas: curto=203.1ms±2.4%, denso=194.0ms±1.9%, longo=196.2ms±3.1%
```

Numa máquina compartilhada, 2–4% é normal. **Uma melhoria de 3% não é
distinguível de ruído aqui.** Se mediu +2% e quer commitar, meça de novo; se
continuar em +2%, trate como empate.

O framework aceita empates (a política é "iguala ou melhora"), então um refactor
neutro que abre caminho para o próximo ganho é commitável — mas descreva-o como
refactor, não como melhoria.

## A média geométrica é uma restrição

Ganhar 20% em `longo` e perder 20% em `curto` **piora** o score. Os três regimes
diferem em quantos grupos existem e quão grandes eles são, que é exatamente a
dimensão em que as estratégias de ordenação se separam. Quando um regime
regride, quase sempre a mudança está explorando a forma de um dos datasets.

## Cuidado registrado

Este alvo foi construído depois de o laboratório descobrir que um candidato pode
ganhar score **sem fazer o trabalho** — memoizando a saída. As três camadas de
defesa estão ligadas aqui desde o primeiro dia: caminho novo e módulo novo a
cada execução medida, e proibição de escrever em disco. A história completa está
em `docs/TARGET_DESIGN.md` §3b.

## Custo de uma avaliação

Cerca de 4 s para o seed, menos conforme você acelera. Use `./avo-eval` à
vontade antes de submeter. Submeter sem medir é chute, e o chute entra no
lineage junto com o resto.
