# Medição: em que delta acreditar

## Como o número é produzido

Três regimes, todos sobre uma **cópia** do banco congelado. A cópia acontece
fora do relógio: o que se mede é SQL, não `cp`.

| regime | o que entra no relógio |
|---|---|
| `frio` | `setup.sql` **mais** as quatro janelas trimestrais de 2024, num banco recém-copiado |
| `quente` | as mesmas quatro janelas, com o banco já preparado |
| `larga` | uma consulta só: 2023 inteiro, `:top_n` mais fundo |

Em cada regime, uma execução de aquecimento é descartada e quatro são
cronometradas; a **mediana** vira o número do regime, e a métrica é `1 / mediana`.
O score final é a média geométrica dos três.

Mediana e não melhor-de-N de propósito: o melhor-de-N recompensa variância, e a
maneira mais barata de melhorar o melhor-de-N é rodar mais vezes, não ficar mais
rápido.

Aquecimento descartado de propósito: a primeira execução depois da cópia paga
cache de página do arquivo novo. Isso é uma constante do sistema, não uma
propriedade da sua consulta.

O regime frio mede um lote de quatro janelas, e não uma, porque é assim que um
relatório é rodado — e porque com uma janela só nenhum índice jamais se pagaria,
e o alvo ensinaria "nunca crie índice", que é a lição errada.

## `frio` contra `quente` é a tensão do alvo

`setup.sql` conta inteiro no `frio` e não conta no `quente` nem no `larga`. A
média geométrica dos três resolve o conflito assim:

- índice que a consulta usa: sobe `quente` e `larga` mais do que afunda `frio`;
- índice que ninguém usa: afunda `frio` e não volta;
- índice do mundo inteiro: afunda `frio` catastroficamente e o `quente` não
  compensa.

`larga` existe por outro motivo: punir o plano que só funciona na faixa curta. Um
`:top_n` maior e doze meses em vez de três mudam as cardinalidades, e um plano
afinado para o trimestre costuma aparecer ali.

## Quanto de ruído esperar

O avaliador reporta o coeficiente de variação por regime em `notes`:

```
medianas: frio=783.0ms±3.8%, larga=672.0ms±7.2%, quente=878.0ms±1.5%
```

Nesta máquina, 2% a 8% é o normal, e o `larga` é o mais ruidoso porque cada
execução cronometrada é uma consulta só, sem média interna. **Uma melhoria de 5%
não é distinguível de ruído neste setup.** Se você mediu +4% e quer commitar,
meça de novo; se continuar em +4%, trate como empate, não como ganho.

Duas mudanças deste alvo estão sabidamente nessa faixa: trocar
`COUNT(DISTINCT order_id)` por `COUNT(*)` e tirar a junção com `customers` de
dentro da agregação. As duas são melhorias de forma defensáveis e nenhuma das
duas aparece no relógio. Isso não é defeito do alvo — é o que medir serve para
descobrir. Descreva-as como refactor, não como ganho.

O framework aceita empates (a política é "iguala ou melhora"), então um refactor
neutro que abre caminho para o próximo ganho é commitável.

## A média geométrica é uma restrição, não um detalhe

Ganhar 30% em `quente` e perder 30% em `frio` **piora** o score. A média
geométrica pune a assimetria: recompensa a mudança que melhora os três regimes
um pouco mais do que a que melhora um muito. Quando um regime regride, diga por
quê no `NOTES.md` — quase sempre é `setup.sql` cobrando o preço, ou um plano que
depende da cardinalidade de uma janela específica.

## Custo de uma avaliação

Cerca de 12s para o seed, menos conforme a consulta melhora. `./avo-eval` de
dentro do run dir é barato: use antes de submeter, sempre. Submeter sem medir é
chute, e o framework registra o chute no lineage junto com o resto.

## Quando o número sobe e você não acredita

Três verificações antes de comemorar:

1. `EXPLAIN QUERY PLAN` mudou como você esperava? Um ganho sem mudança de plano
   costuma ser ruído.
2. O índice que você criou aparece no plano? Índice não usado é só custo no
   `frio`.
3. O `frio` acompanhou? Ganho que só existe no `quente` é `setup.sql` sendo pago
   por alguém — e o alvo cobra.
