# Contrato de `sessionize` — a verdade sobre a saída

```python
sessionize(path: str) -> dict[str, dict]
```

## Entrada

JSONL, **embaralhado**. Cada linha é um evento com dez campos; a sessionização
usa dois: `user_id` (str) e `ts` (int, segundos epoch). Os outros oito existem
porque existem no mundo.

## Chave

`f"{user_id}|{indice}"`. O índice começa em **0 para cada usuário** e cresce em
ordem cronológica dentro dele. Não é um contador global.

## Valor

| campo | tipo | definição |
|---|---|---|
| `n` | int | quantidade de **eventos** na sessão |
| `inicio` | int | menor `ts` da sessão |
| `fim` | int | maior `ts` da sessão |

## A fronteira da sessão — leia duas vezes

Uma sessão termina quando o intervalo até o próximo evento do mesmo usuário é
**maior que 1800 segundos**.

```
delta > 1800   fecha a sessão
delta == 1800  MANTÉM a sessão aberta
```

Exatamente 1800 mantém. Trocar `>` por `>=` produz uma implementação que acerta
em quase todo dado real e erra exatamente nos pares que estão a 1800 s de
distância — e o dataset de gate tem esses pares de propósito. O gerador se
recusa a escrever um `gate_adv` sem eles.

## Ordenação

`ts` é um **inteiro** e ordena como inteiro. Ordená-lo como texto dá a mesma
resposta enquanto todos os timestamps tiverem o mesmo número de dígitos — o que
é verdade em qualquer dado limpo e falso no `gate_adv`, que tem um usuário com
timestamps de magnitudes diferentes.

**O que o contrato não fixa, de propósito:** a ordem entre eventos do mesmo
usuário com o **mesmo** `ts`. Ela é inobservável — `n` conta eventos, `inicio` e
`fim` são valores de `ts`, e eventos empatados têm delta zero. Qualquer ordem
dá o mesmo resultado, então não há desempate a respeitar.

## Casos que o gate exercita

- intervalo de exatamente 1800 s, e de 1801 s
- vários eventos do mesmo usuário no mesmo segundo
- usuário com um único evento no dataset inteiro
- `user_id` com acento, e um id que é prefixo de outro
- timestamps de magnitudes diferentes no mesmo usuário

## Restrições

- Somente a biblioteca padrão, verificado estaticamente antes de executar.
- Não escreva em disco durante a medição — é bloqueado e reprova.
- O dataset é congelado; `dataset.lock.json` guarda o SHA256 de cada arquivo.
