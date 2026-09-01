# STATUS — verificação do ambiente (Sessão 0 do RUNBOOK)

**Data:** 2026-09-01
**Máquina:** container Linux, 4 vCPU (Intel(R) Xeon(R) Processor @ 2.80GHz), 15 GB RAM
**Python:** Python 3.11.15

## `vendor/avo.lock`

Fixado:  `f6dad9e639d3c9e5d5ac9ccacbe076d82cfa39d2`
Checkout: `f6dad9e639d3c9e5d5ac9ccacbe076d82cfa39d2`

Conferem. O harness rodando é o auditado.

## 1. Testes do upstream

```
................................................                         [100%]
48 passed in 5.41s
```

## 2. `make test`

```

================== 121 passed, 4 skipped in 106.17s (0:01:46) ==================
```

Os 4 `skipped` são declarados, não silenciosos: `sql_agg` e `dedupe_match`
declaram `SEM_DEFESA_DE_MEDICAO` com o motivo (o primeiro evolui SQL, não módulo
Python; o segundo não cronometra o candidato), e os testes de memoização
ponta-a-ponta não se aplicam a eles.

## 3. `avo-lab verify`

```
ok   csv_normalize
       ok   target.yaml                  3 arquivos de KB
       ok   dataset.lock                 4 arquivo(s) conferem com o lock
       ok   gate (--selftest)            18 mutantes rejeitados
       ok   dimensionamento (--budget)   avaliação do seed custa 5.3s; execução mais rápida 106ms — dimensionamento saudável
ok   dedupe_match
       ok   target.yaml                  3 arquivos de KB
       ok   dataset.lock                 7 arquivo(s) conferem com o lock
       ok   gate (--selftest)            13 mutantes rejeitados
       ok   dimensionamento (--budget)   avaliacao do seed custa 9.8s — dimensionamento saudável
ok   etl_agg
       ok   target.yaml                  3 arquivos de KB
       ok   dataset.lock                 4 arquivo(s) conferem com o lock
       ok   gate (--selftest)            9 mutantes rejeitados
       ok   dimensionamento (--budget)   avaliação do seed custa 3.0s; execução mais rápida 137ms — dimensionamento saudável
ok   sql_agg
       ok   target.yaml                  3 arquivos de KB
       ok   dataset.lock                 2 arquivo(s) conferem com o lock
       ok   gate (--selftest)            21 mutantes rejeitados
       ok   dimensionamento (--budget)   avaliação do seed custa 8.3s; execução mais rápida 110ms — dimensionamento saudável

4/4 alvos válidos
```

## Veredito

**VERDE.** As três verificações passam.

Nenhum `eval.py` foi alterado para fazer a verificação passar — que é a única
forma de "consertar" um gate que este laboratório proíbe. O hook
`.claude/hooks/protect_arbiter.sh` bloquearia a tentativa de qualquer forma.

## Custo de avaliação por alvo (o que a Falha 2 cobra)

| alvo | seed | execução mais rápida | mutantes |
|---|---|---|---|
| `etl_agg` | 3,0s | 137ms | 9 |
| `csv_normalize` | 5,3s | 106ms | 18 |
| `sql_agg` | 8,3s | 110ms | 21 |
| `dedupe_match` | 9,8s | — (métrica é F1, não tempo) | 13 |

Todos dentro da faixa de 3–25s. Um passo do agente custa segundos, não minutos.

## Próximo

Sessão 1 do `docs/RUNBOOK.md`: `make run TARGET=etl_agg STEPS=15`.
