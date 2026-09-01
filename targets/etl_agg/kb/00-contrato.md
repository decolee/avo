# Contrato de `transform` — a verdade sobre a saída

```python
transform(path: str) -> dict[str, dict]
```

## Chave

`f"{account}|{ccy}"`, por exemplo `"ACC00001|BRL"`. Um grupo por par
conta×moeda. A **ordem** das chaves no dict devolvido não importa; o conjunto
sim.

## Valor

| campo | tipo | definição |
|---|---|---|
| `n` | int | contagem de **todas** as linhas do grupo, qualquer que seja o status |
| `gross` | float | soma de `amount` de **todas** as linhas, arredondada a 2 casas |
| `net` | float | soma de `amount` **apenas** das linhas com `status == "settled"`, arredondada a 2 casas |
| `last_ts` | int | maior `ts` do grupo |

Três leituras erradas que o gate rejeita explicitamente, porque são as que um
engenheiro apressado realmente faz:

- `n` contando só as liquidadas — não: `n` conta tudo.
- `net` incluindo `pending` — não: só `settled`. `pending` e `void` entram em
  `gross` e ficam fora de `net`.
- Agrupar só por conta — não: a moeda faz parte da chave.

## Arredondamento — leia duas vezes

`gross` e `net` são arredondados a 2 casas **no final**, uma única vez, sobre a
soma completa do grupo. Arredondar a cada acumulação:

```python
a["gross"] = round(a["gross"] + row["amount"], 2)   # ERRADO
```

produz um número diferente. Cada arredondamento intermediário descarta até meio
centavo, e num grupo de algumas dezenas de linhas com seis casas decimais o
desvio acumulado passa de um centavo. O gate mede isso contra a soma verdadeira
e reprova.

O valor devolvido também precisa **ser** um valor de dois decimais: devolver a
soma crua, sem arredondar, reprova mesmo estando "mais correto".

## Como a correção é decidida

Num dataset adversarial separado (`data/gate_adv.jsonl`), nunca nos dados de
performance. Ele tem seis casas decimais, notionais de fundo na faixa de 1e8 —
onde `float32` já tem erro de ~8 unidades — e casos de borda explícitos.

Para cada grupo, o gate compara o seu número com a **soma verdadeira**
(`math.fsum`, que é a soma exatamente arredondada) e aceita um desvio de até
meio centavo mais uma folga proporcional à magnitude do grupo. Isso quer dizer:

- somar da esquerda para a direita, com `sum()` ou com `fsum`, tanto faz — o
  erro é da ordem de 1e-10 e passa;
- arredondar durante a acumulação erra por centésimos e **não** passa.

O gate julga a sua lógica, não a ordem em que você somou.

## O que NÃO é contrato — leia antes de otimizar o parsing

Estas propriedades valem para os arquivos que existem hoje e **não** fazem parte
do contrato. Um candidato pode observá-las; não pode depender delas.

| propriedade do arquivo | é contrato? |
|---|---|
| os dezesseis campos aparecem sempre na mesma ordem | **não** |
| um valor numérico é sempre seguido de vírgula | **não** — em JSON também pode vir `}` |
| todos os registros têm todos os campos | **não** |
| `account`, `ccy` e `status` nunca têm escape | **sim**, o ledger garante |
| a chave de saída é `"<account>|<ccy>"` | **sim** |

As duas primeiras já foram exploradas de verdade. Um candidato que buscava cada
campo a partir do fim do anterior — e que portanto assumia ordem — media +28,6%
sobre o melhor candidato honesto e **passava no gate**, porque o `gate_adv` e os
`perf_*` saíam do mesmo gerador, com a mesma ordem.

O `gate_adv` agora permuta a ordem das chaves em parte dos registros, e um
candidato posicional falha logo na primeira linha. A história completa está em
`experiments/REWARD_HACKING.md`.

Extração dirigida continua valendo a pena — vale **+61,4%** sobre `json.loads`
quando feita corretamente. O que não vale é economizar em cima da forma do
arquivo.

## Restrições

- Somente a biblioteca padrão. Verificado estaticamente antes de executar.
- O dataset é congelado: `dataset.lock.json` guarda o SHA256 de cada arquivo.
- Não escreva nada em disco; `transform` só lê.
