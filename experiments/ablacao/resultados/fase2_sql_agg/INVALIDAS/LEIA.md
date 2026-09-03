# Sementes arruinadas pelo ambiente — não são dado

Numa janela de `API Error: 529 Overloaded` (lado do servidor), as sessões de
agente passaram a morrer no primeiro turno. O harness continuou o laço: avaliou a
árvore de trabalho intocada, o gate aceitou ou rejeitou, e a semente terminou com
um número.

```
full s5 (4,67x)   passo 1: US$ 5,25 / 50 turnos      <- trabalho real
                  passo 2: US$ 1,18 / 12 turnos      <- parcial
                  passos 3-8: US$ 0,003 / 1 turno    <- mortos
full s6 (1,07x)   passos 1-8: US$ 0,003 / 1 turno    <- mortos
```

**Por que o s5 também sai, apesar de 4,67× parecer normal.** Ele mediu um `full`
de um passo e meio, não de oito. O número é plausível e mede outra coisa — e é
justamente por parecer normal que ele é mais perigoso que o s6.

**O estrago que teria causado.** Com o s6 dentro, o braço ia de
`4,767 ± 0,299` (n=6) para `4,239 ± 1,423` (n=7): a média cai 11% e o desvio
triplica. Um desvio inflado assim empurra o MDE para cima e transforma qualquer
resultado em "não distinguível" — o experimento se autossabota sem que nada fique
vermelho.

**O conserto.** `runner._semente_invalida()` condena a semente quando metade ou
mais dos passos custou menos de US$ 0,05 sem ter sido morta por timeout. Uma
sessão real neste alvo custa US$ 2 a US$ 5 e uma morta no primeiro turno custa
US$ 0,003 — duas ordens de grandeza de cada lado do corte, sem zona cinzenta.
Semente condenada **não é gravada** (gravada, contaria como feita e nunca seria
refeita), o run dir vem para cá, e o runner espera 10 minutos antes de tentar de
novo, porque a causa típica passa sozinha.

Passo morto por **timeout** é caso diferente e continua valendo: ali o agente
trabalhou os 20 minutos e o gate julga o que ele deixou (ver
`FASE2_SQL_AGG.md` §8).
