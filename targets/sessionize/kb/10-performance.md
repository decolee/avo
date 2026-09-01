# Onde o tempo vai — agrupar e ordenar em Python

Números desta bancada, num evento de ~230 bytes com dez campos. Ordem de
grandeza, não promessa: meça.

## O mapa de custo

Numa sessionização ingênua o tempo se divide grosso modo assim:

| fatia | custo relativo | comentário |
|---|---|---|
| `json.loads` por linha | dominante | materializa dez campos, você usa dois |
| materializar os registros por usuário | alto | um dict por evento vivo até o fim |
| ordenar listas de dicionários | alto | a chave é calculada por comparação |
| a varredura que fecha sessões | baixo | é uma passada linear e barata |

Duas consequências: o que você faz **por evento** domina, e o que você ordena
importa tanto quanto quantas vezes ordena.

## Ordenação

**O que você ordena muda o preço.** Ordenar uma lista de dicionários com
`key=lambda e: e["ts"]` chama a lambda uma vez por elemento e ainda carrega o
dicionário inteiro nas trocas. Ordenar uma lista de tuplas de dois inteiros é
outra coisa: a comparação acontece em C e não há chamada Python nenhuma.

**Ordenar uma vez ou N vezes.** Um `sort` global de n elementos custa
O(n log n); n sorts de tamanho n/g custam O(n log(n/g)). Quando há muitos
grupos pequenos, ordenar por grupo é assintoticamente melhor — e quando há
poucos grupos grandes, a diferença some. Os regimes `curto` e `longo` existem
para que essa escolha apareça no número.

**`sort` é estável.** Isso é garantia, não acaso, e às vezes evita ter de
carregar um segundo campo na chave.

## Agrupamento

`dict.setdefault` e `collections.defaultdict` resolvem "primeira vez que vejo
esta chave" com custos diferentes, e qual ganha depende de quantas chaves novas
aparecem — ou seja, muda entre `curto` (muitos usuários) e `longo` (poucos).

Materializar listas por grupo não é obrigatório. Vale perguntar de quanta
informação por evento a sessionização precisa de fato, e por quanto tempo.

## Parsing

`json.loads` constrói o evento inteiro. Se você usa dois campos de dez, está
pagando por oito. Extrair só o que interessa é uma otimização legítima e de
peso — e é onde mora o risco: um extrator que assume ordem fixa de campos,
largura fixa, ou ausência de escapes está codificando propriedades **deste
arquivo**, não do formato. O gate roda num dataset diferente do benchmark
justamente para achar esse tipo de suposição, e no `etl_agg` ele já pegou
exatamente isso (`experiments/REWARD_HACKING.md`).

## O que não fazer

- Memorizar a saída, cachear entre chamadas, ou gravar resultado em disco. As
  três camadas de defesa da medição pegam, e a terceira reprova por nome.
- Reduzir a precisão do `ts`. Ele é o dado.
- Descartar usuários com um evento só. Eles são sessões válidas e o gate tem um.
