# Piloto do eixo do modelo — resultado

Executado contra `FASE_MODELO.md`, pré-registrado antes do primeiro dado.
**US$ 16,60, 1,9 h, 3 runs.** O braço de referência (5 sementes de `claude-opus-5`)
já estava pago pela ablação de 2026-09-06, então só o modelo novo custou.

## O número

| modelo | n | média | dp | cv | US$/run | h/run | **× por US$** |
|---|---|---|---|---|---|---|---|
| `claude-opus-5` | 5 | **7,396** | 0,328 | 4,4% | 25,18 | 1,59 | 0,294 |
| `claude-sonnet-5` | 3 | **5,363** | 0,124 | 2,3% | 5,53 | 0,63 | **0,969** |

```
sonnet: 5,321 · 5,266 · 5,502
opus:   7,899 · 7,369 · 7,479 · 7,189 · 7,042
```

Δ = **2,033×**, ou **27,5%** da base. IC95 bootstrap [+1,767, +2,323], p de
permutação 0,016.

**Para comparar:** o maior contraste de andaime que esta bancada mediu em três
experimentos e US$ 883 foi de **5,7%**, com intervalo cruzando o zero. Este é
**cinco vezes maior** e o intervalo não chega perto do zero.

> Dado de piloto **não entra em análise formal** — desvio 1 do pré-registro. Os
> números acima dimensionam; não são o experimento. O `n` necessário sai 0,2, o
> que na prática quer dizer "qualquer n sensato distingue".

## O critério de parada, aplicado

O pré-registro fixou: `n ≤ 8` → pagável, rodar 3 modelos. Saiu **0,2**. Pagável.

## Mas o efeito está confundido com orçamento — e isso foi declarado antes

O desvio 3 do pré-registro dizia, antes de existir dado:

> Orçamento igualado por PASSOS, não por tokens. Herda a limitação da Fase 3 e ela
> é **pior aqui**: modelos diferentes gastam tokens e relógio muito diferentes
> pelos mesmos 8 passos. Um resultado a favor do modelo mais caro é, em parte, um
> resultado sobre orçamento.

Foi exatamente o que aconteceu. Pelos mesmos 8 passos, o Opus gastou
**US$ 25,18 contra US$ 5,53** — 4,6× mais dinheiro — e 2,5× mais relógio. Parte
dos 27,5% é compute, não capacidade, e **não dá para saber que parte com estes
dados.**

E a leitura inverte quando o eixo é dinheiro: por dólar gasto, o Sonnet entrega
**0,969× contra 0,294× do Opus — 3,3× mais eficiente.**

Uma nota que o piloto deu de graça: o cv do Sonnet é **2,3%**, metade do do Opus.
O modelo mais barato é também o mais consistente neste alvo.

## O experimento que isto pede — e que NÃO é o que eu tinha pré-registrado

O desenho pré-registrado (3 modelos × n=5, 8 passos) mediria de novo um contraste
confundido, com mais precisão e o mesmo problema. **O piloto existe para mudar o
desenho, e mudou.**

A pergunta certa é uma só, e é decidível:

> **Com orçamento igualado por dólar, o Sonnet alcança os 7,4× do Opus?**

- Se alcançar → a diferença é **orçamento**, e o resultado prático é que o modelo
  barato faz o mesmo trabalho por menos.
- Se estacionar abaixo (digamos 6×) → a diferença é **capacidade**, e o eixo do
  modelo é real.

**Custo:** o Opus gasta US$ 3,15/passo e o Sonnet US$ 0,69. Igualar por dólar dá
ao Sonnet ~36 passos contra os 8 do Opus. A US$ 25/run e n=3, são **~US$ 75 e
~7 h.** O braço do Opus já está pago.

Há um risco de desenho a declarar: o alvo tem 8 movimentos medidos, e 36 passos
podem **esgotá-lo**. Se o Sonnet platôa por falta de alvo e não por falta de
capacidade, o resultado não separa nada. Mitigação: registrar o passo do platô e
comparar com o do Opus — se o Sonnet platôa no mesmo lugar, é o alvo.

## O que este piloto NÃO diz

Nada sobre AGI nem sobre capacidade geral, pelo mesmo motivo declarado no
pré-registro: o alvo tem `f` objetivo e verificável, e essa é por construção a
classe de problema em que a pergunta sobre generalidade não pode ser feita. O que
se mediu é competência estreita em otimização de consultas SQL.

## Reprodução

```
python3 experiments/ablacao/piloto_modelo.py \
    --alvo sql_workload --modelo claude-sonnet-5 --n 3 --passos 8
```

Dados: `experiments/ablacao/resultados/piloto_modelo_claude-sonnet-5/piloto.jsonl`
