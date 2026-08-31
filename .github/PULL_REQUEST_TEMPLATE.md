## O que muda

<!-- Uma frase. Se precisar de tres, provavelmente sao tres PRs. -->

## Como foi verificado

<!-- Cole a saida real. Numero estimado nao entra: chute vira folclore, e
     folclore vira decisao de projeto seis meses depois. -->

```
$ make verify
```

## Checklist

- [ ] `make verify` verde
- [ ] Se mexeu em `targets/*/eval.py` ou em `labkit/`: a mudanca no arbitro esta
      justificada aqui, e o `--selftest` continua verde
      <!-- O hook exige AVO_LAB_ALLOW_ARBITER_EDIT=1 para essa edicao. Diga por
           que era legitima: mutante novo, bug do gate, tolerancia frouxa. -->
- [ ] Se e alvo novo: a checklist do `CONTRIBUTING.md` esta inteira marcada,
      inclusive o headroom medido e o "tentei trapacear e nao consegui"
- [ ] Nenhum numero de desempenho neste PR e estimado
