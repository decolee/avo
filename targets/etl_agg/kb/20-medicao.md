# Medição: em que delta acreditar

## Como o número é produzido

Para cada um dos três regimes: uma execução de aquecimento é descartada, depois
cinco execuções são cronometradas e a **mediana** é usada. O throughput do
regime é `1 / mediana`. O score final é a média geométrica dos três.

Mediana e não melhor-de-cinco de propósito: o melhor-de-N recompensa variância,
e a maneira mais barata de melhorar o melhor-de-N é rodar mais vezes, não ficar
mais rápido.

Aquecimento descartado de propósito: a primeira execução paga cache de página do
arquivo e aquecimento de import. Isso é uma constante do sistema, não uma
propriedade do seu código.

## Quanto de ruído esperar

O avaliador reporta o coeficiente de variação por regime em `notes`, assim:

```
medianas: narrow=235.3ms±1.3%, skew=243.3ms±1.2%, wide=262.0ms±2.7%
```

Numa máquina compartilhada, 2–4% é normal. **Uma melhoria de 3% não é
distinguível de ruído neste setup.** Se você mediu +2% e quer commitar, meça de
novo; se continuar em +2%, ainda assim trate como empate, não como ganho.

O framework aceita empates (a política é "iguala ou melhora"), então um refactor
neutro que abre caminho para o próximo ganho é commitável — mas descreva-o como
o que é, um refactor, e não como uma melhoria.

## A média geométrica é uma restrição, não um detalhe

Ganhar 20% em `narrow` e perder 20% em `wide` **piora** o score. A média
geométrica pune a assimetria: ela recompensa a mudança que melhora os três
regimes um pouco mais do que a que melhora um muito. Quando um regime regride,
diga por quê no `NOTES.md` — quase sempre é um sinal de que a mudança está
explorando a forma de um dos datasets em vez do formato.

## Custo de uma avaliação

Cerca de 3s para o seed, menos conforme você acelera. `./avo-eval` de dentro do
run dir é barato: use antes de submeter, sempre. Submeter sem medir é chute, e
o framework vai registrar o chute no lineage junto com o resto.
