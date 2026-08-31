# RESULTS — `etl_agg`, run de exemplo

**Harness:** `gatordevin/avo` @ `f6dad9e6` · **Modo:** sessão · **Passos:** 4 de 6
**Máquina:** container Linux, 4 vCPU — os números absolutos são dela; as razões é
que interessam.

Este run existe para o repositório se demonstrar: é um lineage real, com uma
rejeição real, produzido pelo loop descrito no `RUNBOOK.md`. Nenhum número aqui
foi escrito à mão.

## Lineage

| ver | primary | wide | narrow | skew | Δ | aceito | resumo |
|---|---|---|---|---|---|---|---|
| 0 | 4,163 | — | — | — | — | seed | `x_0`: materializa tudo, reagrupa, 4 travessias por grupo |
| 1 | 6,877 | | | | +65,2% | ✅ | passe único com acumulador em lista |
| 2 | 10,275 | 9,09 | 11,74 | 12,25 | +49,4% | ✅ | extração dirigida dos 5 campos usados |
| — | 0 | | | | — | ❌ | arredondamento durante a acumulação — **gate** |
| 3 | 14,009 | | | | +36,3% | ✅ | busca inline no lugar da auxiliar por campo |

Baseline medida antes do início: `referencia_passe_unico` = 6,445. A v1 mal a
alcança; a v3 fica 117% acima dela.

**Ganho total: +236,5% sobre o seed (3,36×).**

## A rejeição, literal

```
rejected — gate: ACC00000|BRL.gross: soma verdadeira 21424.216176,
obtido 21424.23 (erro 0.0138 > tolerância 0.0050). Arredondar durante a
acumulação em vez de no final produz exatamente este desvio.
discarded diff saved to rejected/step-0003.patch
score    0  correct=False
```

O diff descartado está em `rejected-step-0003.patch`. Correção não vale "um pouco
menos": vale zero.

## Razão de aceitação

3 de 4 = **75%**. O paper reporta ~8% (500+ direções, 40 commits em 7 dias). A
diferença é esperada e informativa: este run cobre os primeiros passos, onde o
headroom óbvio ainda não acabou. Uma razão de 75% sustentada por vinte passos
significaria alvo fácil demais.

## A forma da curva é o ponto

| passo | ganho relativo |
|---|---|
| v0 → v1 | +65,2% |
| v1 → v2 | +49,4% |
| v2 → v3 | +36,3% |

Retornos decrescentes, três movimentos **independentes**, nenhum deles capturando
mais de 38% do ganho acumulado. É a propriedade que torna este alvo utilizável
numa ablação — e é exatamente o que a versão anterior do `etl_agg` **não** tinha,
com 57,8× num único passo e platô imediato depois (`docs/TARGET_DESIGN.md` §3).

Compare com o paper: 40 versões, cinco pontos de inflexão, melhoria em saltos
discretos separados por platôs, e retornos decrescentes de v21 em diante. Em
miniatura, é a mesma forma.

## Onde a curva ainda não estagnou

Não estagnou — o run terminou por limite de passos, não por falta de ideias. O
`NOTES.md` lista o que não foi tentado. O regime `wide` está ~20% atrás dos
outros dois de forma consistente, e ninguém atacou isso.
