# Eixo do modelo — resultado definitivo

Pré-registrado em `FASE_MODELO.md`. Executado em 2026-09-07/08.
**US$ 65,34 e 8,4 h** no braço novo; o de referência já estava pago.

## A pergunta

O piloto de 8 passos mediu o Opus 27,5% acima do Sonnet, mas **igualando por
passos** — e pelos mesmos 8 passos o Opus gastou 4,6× mais dinheiro. O ADENDO
declarou que isso não separava capacidade de orçamento, e fixou o experimento
que separaria:

> Com orçamento igualado por dólar, o Sonnet alcança os 7,4× do Opus?

O Sonnet recebeu **36 passos** contra os 8 do Opus — os mesmos US$ 25,18 por run.

## A resposta: é capacidade, não orçamento

| braço | passos | n | razão (re-medida) | dp | cv |
|---|---|---|---|---|---|
| `claude-opus-5` | 8 | 5 | **6,618** | 0,436 | 6,6% |
| `claude-sonnet-5` | 8 | 3 | **4,738** | 0,191 | 4,0% |
| `claude-sonnet-5` | **36** | 3 | **4,720** | 0,062 | 1,3% |

| comparação | Δ | IC95 | p |
|---|---|---|---|
| Opus × Sonnet-36p — **mesmo dólar** | **+28,7%** | [+1,517, +2,209] | 0,016 |
| Opus × Sonnet-8p — mesmo passo | +28,4% | [+1,484, +2,242] | 0,016 |
| Sonnet-36p × Sonnet-8p — **4,5× o orçamento** | **−0,4%** | [−0,172, +0,172] | **0,90** |

**Dar ao Sonnet 4,5 vezes mais orçamento não comprou absolutamente nada.**
4,738 → 4,720, com intervalo apertado em torno do zero. E a distância para o
Opus com o mesmo dólar é a mesma de antes: ~29%.

O eixo do modelo é real e é grande. **É a única coisa que esta bancada mediu em
quatro experimentos que se distingue do ruído com folga.**

## O alvo não esgotou — e a prova está no próprio experimento

O ADENDO declarou o risco: 36 passos num alvo de 8 movimentos podem esgotá-lo, e
aí o platô do Sonnet não separaria nada.

| braço | aceitos | último aceite |
|---|---|---|
| `opus-8p` | 5–7 de 8 | passo 7–8 (88–100% do orçamento) |
| `sonnet-36p` | 8–10 de 36 | passo 12, 19 e 30 (33%, 53%, 83%) |

O Sonnet parou de achar melhorias com **um a dois terços do orçamento ainda por
gastar**, em 2 das 3 sementes. E a refutação decisiva não precisa disso: **o Opus
alcança 6,618× no mesmo alvo**, então existe headroom bem acima dos 4,72× onde o
Sonnet estaciona. O platô é do modelo, não do alvo.

O Opus, ao contrário, ainda estava melhorando quando o orçamento acabou — último
aceite no passo 7 ou 8 de 8 nas cinco sementes.

## O defeito que este experimento encontrou (nº 18)

O resultado acima está sobre a razão **re-medida**. A razão como o harness a
registra estava contaminada, e o experimento só ficou legível depois de consertar
isso.

`melhoria_relativa = primary_final / primary_seed`. O `primary_seed` é medido uma
vez, no início do run, sobre um artefato de seed **idêntico** em todos eles. Ao
longo dos 11 runs deste eixo ele variou assim:

```
medido no run (original):  media 1,217  cv 19,6%  min 0,913  max 1,536  -> 1,68x
re-medido hoje, em bloco:  media 1,519  cv  4,4%  min 1,455  max 1,700  -> 1,17x
```

**1,68× de variação no mesmo artefato**, contra 1,17× quando as medidas são
tomadas em sequência imediata. E não é ruído branco: os três runs do piloto de 8
passos do Sonnet mediram seed 0,94–0,95, enquanto os do Opus mediram 0,91–1,31 e
os de 36 passos 1,46–1,54. É deriva **por bloco de execução**.

Isto é o **defeito 9 reaparecendo numa forma nova**, e a nuance importa:

- Numa ablação de braços **intercalados** (a Fase 3), o ruído do seed é comum a
  todos os braços e a razão o cancela. Foi por isso que, testando lá, fixar o
  denominador **piorava** o cv em 3 dos 4 braços. Aquela conclusão continua certa
  para aquele desenho.
- Entre **experimentos** de dias e durações diferentes, não há nada em comum para
  cancelar, e a razão vira uma medida do estado da máquina.

Sem a re-medição, este experimento teria reportado o Sonnet-36p em 5,180× contra
5,363× do Sonnet-8p — a mesma conclusão qualitativa, mas por sorte: os dois
números estavam inflados por fatores diferentes.

**Regra que sai daqui:** comparação entre experimentos exige re-medição pareada
dos artefatos finais, com a máquina ociosa. `remedir_modelo.py` faz isso e custa
4 minutos.

## O que isto NÃO diz

Nada sobre AGI nem capacidade geral. O alvo é otimização de consultas SQL com `f`
objetivo e verificável — por construção, a classe de problema em que a pergunta
sobre generalidade não pode ser feita. O que se mediu é competência estreita.

E não diz que o Sonnet é a escolha errada: por dólar gasto ele entrega mais
(0,969× contra 0,294× do Opus no piloto de 8 passos). Diz que **existe um teto
que dinheiro não compra** — e que, neste alvo, ele fica ~29% abaixo do Opus.

## O quadro completo, quatro experimentos

| eixo | contraste | efeito | distinguível? |
|---|---|---|---|
| andaime | componentes (`sql_agg`) | −3,5% a −4,5% | não |
| andaime | `full` × `greedy` (n=11) | +4,9% | não |
| andaime | componentes (`sql_workload`, n=5) | −5,5% a +5,7% | não |
| **modelo** | **Opus × Sonnet, mesmo dólar** | **+28,7%** | **sim (p=0,016)** |
| orçamento | Sonnet 36p × 8p | −0,4% | não (p=0,90) |

US$ 883 medindo andaime não acharam nada. US$ 65 medindo modelo acharam 28,7%.

## Reprodução

```
python3 experiments/ablacao/piloto_modelo.py --alvo sql_workload \
    --modelo claude-sonnet-5 --n 3 --passos 36 \
    --saida experiments/ablacao/resultados/dolar_sonnet_36p

# com a maquina OCIOSA:
python3 experiments/ablacao/remedir_modelo.py --alvo sql_workload
```

Dados: `resultados/dolar_sonnet_36p/piloto.jsonl` e
`resultados/remedido_modelo.jsonl`.
