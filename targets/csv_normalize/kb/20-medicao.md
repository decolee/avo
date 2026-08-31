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

**O caminho entregue muda a cada execução.** É um symlink novo apontando para o
mesmo arquivo. Não muda nada para quem lê o arquivo e derruba quem memoiza a
saída indexada pelo caminho. Além disso o avaliador compara a sua mediana com o
custo de simplesmente ler os bytes da entrada: uma execução mais rápida que isso
é reprovada por implausibilidade, porque nenhuma implementação que processa os
dados consegue ser mais rápida que lê-los.

## Os três regimes e por que eles são diferentes

| regime | forma do dado | o que ele revela |
|---|---|---|
| `limpo` | ASCII, data ISO, decimal simples, ~6.200 documentos | quanto vale um caminho rápido para o caso comum |
| `sujo` | acento combinante, espaço estranho, decimal BR e US, sentinelas, BOM | se esse caminho rápido sabe cair fora sem quebrar |
| `dup` | 180 documentos para 9.000 linhas | quanto vale não fazer trabalho que será descartado |

São três **formas** de dado, não três repetições da mesma. Uma mudança que
acelera `limpo` porque assume ASCII e regride `sujo` porque o caminho geral ficou
mais caro aparece imediatamente, e a média geométrica cobra a conta.

## Quanto de ruído esperar

O avaliador reporta o coeficiente de variação por regime em `notes`, assim:

```
medianas: dup=471.4ms±2.1%, limpo=401.8ms±1.4%, sujo=457.9ms±2.6%
```

Numa máquina compartilhada, 2–4% é normal. **Uma melhoria de 3% não é
distinguível de ruído neste setup.** Se você mediu +2% e quer commitar, meça de
novo; se continuar em +2%, ainda assim trate como empate, não como ganho.

O framework aceita empates (a política é "iguala ou melhora"), então um refactor
neutro que abre caminho para o próximo ganho é commitável — mas descreva-o como
o que é, um refactor, e não como uma melhoria. Tirar as expressões regulares do
laço é exatamente esse caso: vale ~3%, ou seja, nada, e mesmo assim é o passo que
permite trocá-las por métodos de string depois.

## A média geométrica é uma restrição, não um detalhe

Ganhar 20% em `dup` e perder 20% em `sujo` **piora** o score. A média geométrica
pune a assimetria: ela recompensa a mudança que melhora os três regimes um pouco
mais do que a que melhora um muito. Quando um regime regride, diga por quê no
`NOTES.md` — quase sempre é sinal de que a mudança está explorando a forma de um
dos datasets em vez do formato.

O caso clássico aqui é a deduplicação preguiçosa: adiar a normalização do nome e
da UF para depois de saber quem venceu é um ganho enorme em `dup`, quase nulo em
`limpo` (onde quase toda linha é vencedora) e legítimo nos dois. Já um parser
que assume que todo campo é ASCII ganha em `limpo`, regride em `sujo` e reprova
no gate — a mesma mudança medida em três lugares dá três respostas, e é para
isso que os três regimes existem.

## Custo de uma avaliação

Cerca de 8 s para o seed, menos conforme você acelera. `./avo-eval` de dentro do
run dir é barato: use antes de submeter, sempre. Submeter sem medir é chute, e o
framework vai registrar o chute no lineage junto com o resto.

Para calibrar expectativa: o headroom medido deste target é de cerca de **4,4x**
entre o seed e uma implementação bem feita, distribuído em seis movimentos
independentes, sendo os dois maiores de ~1,6x cada. Não existe aqui um único
movimento que capture o ganho inteiro. Se o seu primeiro passo deu 4x, ou você
achou algo que eu não achei — ótimo, documente — ou você está medindo um cache.
