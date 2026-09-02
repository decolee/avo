# Fase 2A — `full` contra `greedy` no `sql_agg`

**Pré-registro.** Este documento e o dimensionamento abaixo são anteriores à
primeira linha de dados; o histórico do git prova. É a terceira tentativa de
responder a mesma pergunta, e as duas anteriores falharam por motivos que agora
estão consertados e verificados.

## 1. O que mudou desde as tentativas anteriores

| tentativa | por que falhou | conserto |
|---|---|---|
| `ABLATION.md` | alvo saturado; supervisor nunca disparou | alvo novo; `--stagnation-window 2` |
| `CONTROLE.md` | idem, **e** os agentes não conseguiam medir | `--allowed-tools`, verificado |

A terceira condição — dimensionar antes de gastar — é o que este documento faz.

## 2. O piloto (`resultados/piloto_sql_agg/`)

Não é este experimento: nenhuma hipótese foi testada nele, e nada do que saiu
dele entra na análise. Ele mediu a variância para dimensionar o que vem agora.

**`greedy`, n=5, com o avaliador funcionando:**

```
4.33x  4.36x  4.64x  4.67x  4.76x     media 4.552   desvio 0.193   CV 4.2%
```

Sete a onze medições por sessão, zero recusas de permissão, US$ 1,57 e ~350 s por
sessão. Cinco de cinco corretas, cinco de cinco com código alterado.

O contraste com o run cego do mesmo piloto é o achado que dimensiona tudo:

| | média | desvio | recusas/sessão |
|---|---|---|---|
| cego | 3,47× | **1,362** | 12 a 21 |
| enxergando | 4,55× | **0,193** | 0 |

**A variância caiu 7×.** A bimodalidade do run cego — dois grupos, ~4,5× e
~1,95×, com o *mesmo* índice em todas as cinco sementes — não era propriedade do
alvo: eram agentes chutando a forma da consulta sem poder conferir. Acesso à
medição não deixou o agente mais capaz; deixou-o **confiável**.

**`full`, n=1, 8 passos, janela 2:**

| passo | ganho | acumulado | US$ | supervisor |
|---|---|---|---|---|
| 1 | 3,77× | 1 033 s | 4,97 | |
| 2 | 4,32× | 2 235 s | 4,97 | |
| 3 | 4,32× | 3 436 s | 4,97 | |
| 4 | **4,78×** | 4 110 s | 7,87 | |
| 5–6 | 4,78× | 6 388 s | 11,95 | |
| 7–8 | 4,78× | 8 627 s | **21,18** | **disparou 2×** |

Duas observações, ambas n=1 e ambas inéditas neste laboratório. O supervisor
**disparou pela primeira vez** — na Sessão 3 foram 36 passos elegíveis e zero
disparos — e os dois disparos vieram depois do platô já estabelecido, sem
resgatar nada. E **US$ 13,31 dos US$ 21,18 compraram platô**: o ganho parou no
passo 4.

Cortar para 4 passos economizaria 63% do custo e tiraria o supervisor do
experimento — que é justamente a peça que nunca foi observada. Fica em 8.

## 3. O desenho

| braço | configuração | n | US$/semente |
|---|---|---|---|
| `full` | 8 passos, `--stagnation-window 2`, timeout 20m | 11 | ~21,18 |
| `greedy_nat` | uma sessão, parada natural, teto de 8 627 s | 11 | ~1,57 |

**Custo previsto: ~US$ 250. Relógio previsto: ~28 h.** Sequencial, braços
intercalados, ordem sorteada dentro de cada rodada, um commit por semente.

Os dois braços recebem `--allowed-tools Bash,Read,Edit,Write,Glob,Grep,...` —
idêntico, explícito, e verificado na transcrição antes da análise.

## 4. Poder, calculado antes

Com desvio de 0,193 sobre média 4,55 (n ≈ 2·(2,8·s/Δ)², 5%, poder 80%):

| efeito | em ganho | n por braço |
|---|---|---|
| 5% | 0,23× | **11** |
| 10% | 0,46× | 3 |
| 15% | 0,68× | 1 |

O piloto já sugere onde a diferença está: `full` 4,78× contra `greedy` 4,55×, ou
**+5%**, por 13× mais dinheiro e 25× mais relógio. n=11 é escolhido para
distinguir exatamente esse tamanho de efeito. Se ele for menor que isso na
amostra maior, o experimento dirá "abaixo do MDE" e não "empate".

O desvio usado é o do `greedy`. O do `full` costuma ser menor, porque o gate
trunca a amostra ruim — então o dimensionamento é conservador.

## 5. Análise pré-registrada

A mesma de `analise_controle.py`, sem mudanças: ganho relativo ao seed da própria
semente, IC95 por bootstrap de 10 000 reamostragens, p bilateral por permutação,
Holm sobre o conjunto, MDE e n-necessário reportados junto de toda diferença
não significativa, e pareamento por relógio **e** por dólar.

**Antes de analisar**, `destilar_logs.py` roda sobre as transcrições e precisa
sair com código 0. Uma sessão cega não é ruído a mais na amostra: é uma sessão
que não testa o que este documento diz testar.

## 6. O que este experimento não responde

Se o `full` ganhar, a resposta imediata é "ele teve 25× mais relógio". A Fase 2B
(`greedy_cont`, retomado mecanicamente até igualar os 8 627 s) existe para
fechar essa porta, e **não** está sendo rodada agora: pela taxa de retomada
observada no `csv_normalize` (US$ 0,008/s), ela custaria ~US$ 69 por semente,
US$ 760 para n=11. Ela será dimensionada depois de ver 2A, com o efeito real na
mão em vez de um palpite.
