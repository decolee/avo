# Medir sem se enganar

## Quanto custa uma avaliacao

`./avo-eval` de dentro do run dir roda o avaliador inteiro sem tocar no lineage:
gate no banco adversarial, conferencia dos oito relatorios no banco medido, e os
tres regimes. **~14 s** com o seed. Use a vontade — e barato comparado a
submeter uma mudanca que voce nao mediu.

`EXPLAIN QUERY PLAN` e ainda mais barato e responde outra pergunta: nao *quanto*
mudou, mas *por que*. Rode antes de medir.

## Qual delta acreditar

O avaliador reporta o coeficiente de variacao de cada regime nas `notes`
(`quente=848.9ms±1.6%`). Medido nesta maquina, ao longo da construcao do alvo:

| | CV observado |
|---|---|
| dentro de uma avaliacao, por regime | 0,9% a 4,9% |
| entre avaliacoes, na razao candidato/base | 2,0% a 2,7% |

**Abaixo de 3% e empate.** Um passo que move o score em 2% nao mediu nada: ele
mediu a maquina. Isso nao quer dizer que a mudanca seja ruim — quer dizer que
voce ainda nao sabe.

Dois jeitos de sair do empate, nesta ordem:

1. **Meca em par.** Avalie a base e o candidato em sequencia imediata e tome a
   razao dos dois; nunca compare um numero de agora com um numero de meia hora
   atras. A deriva da maquina entre medicoes distantes ja foi grande o bastante,
   neste laboratorio, para inverter uma conclusao inteira.
2. **Olhe o regime, nao so a media.** Uma mudanca real quase sempre aparece
   concentrada em um dos tres. Se o ganho esta espalhado igualmente em `frio`,
   `quente` e `estreito` e nenhum passa do ruido, provavelmente nao ha ganho.

## Os tres regimes discordam de proposito

`frio` cobra a construcao; `quente` e `estreito` cobram o plano, em duas
seletividades diferentes. Uma mudanca no `setup.sql` quase sempre mexe nos tres
em direcoes diferentes, e o numero que conta e a media geometrica.

Um caso concreto que vale internalizar: um indice que voce criou pode aparecer
como **perda** enquanto as consultas que se beneficiariam dele ainda nao estao
escritas de um jeito que o planejador consiga usar. O custo de construir e
imediato e visivel no `frio`; o beneficio depende do resto do candidato. O
inverso tambem acontece — uma reescrita que nao mostra ganho nenhum pode passar
a mostrar depois que o esquema muda.

**Consequencia pratica:** uma medicao negativa aqui nao e um veredito permanente
sobre a mudanca; e um veredito sobre a mudanca *nesta combinacao*. Anote no
`NOTES.md` o que foi medido E contra o que, e volte a testar as ideias
descartadas depois de mudancas grandes. Um beco sem saida anotado sem o contexto
vira folclore, e folclore custa passos.

## Uma coisa que ja foi medida e nao paga

Recortar um indice parcial nas janelas que o avaliador cronometra
(`WHERE order_date >= '2024-01-01'` e variantes) foi tentado em quatro formas
durante a construcao do alvo. Todas ficaram **entre 35% e 40% abaixo** do mesmo
indice sem o recorte de calendario.

A razao e mecanica e esta em `kb/10-sqlite-plano-e-indices.md`: as janelas chegam
como parametros nomeados, o planejador nao conhece o valor deles, e por isso nao
consegue provar que `order_date >= :d0` implica `order_date >= '2024-01-01'`. O
indice e construido, cobrado no `frio`, e nunca usado.

Independentemente disso: especializar o esquema fisico no calendario que o
relogio usa nao e transformacao geral, e o contrato diz que nao vale. O fato de
tambem nao pagar e conveniencia, nao licenca.

## O que saber responder antes de submeter

1. Qual foi a mudanca, em uma frase?
2. Quanto ela mediu, em cada um dos tres regimes?
3. O ganho passa de 3%? Se nao, e empate — e empate commita, mas descreva-o como
   empate.
4. E transformacao geral ou depende da forma deste dado, deste calendario, ou de
   qual banco esta sendo lido?
