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

---

## 7. Desvio operacional declarado: os braços deixaram de ser intercalados

`docs/ABLATION_PROTOCOL.md` §4 exige braços **intercalados**, nunca em bloco, para
que deriva térmica ou de máquina não vire efeito de braço. Este experimento
quebra essa regra, e a razão é de infraestrutura, não de ciência.

**O que aconteceu.** A partir das 20h24 do dia 2, os containers desta plataforma
passaram a ser reciclados com frequência crescente:

| container | duração | o que fechou |
|---|---|---|
| A | 2,7 h | `full` s0 inteiro (8 passos) |
| B | 1,5 h | 4 dos 8 passos do `full` s1 |
| C | 8 min | nada |
| D | 16 min | nada |
| E | 3 min | nada |

Um passo do `full` leva ~18 min de agente. Quando o container vive menos que
isso, **o passo nunca fecha**: cada relançamento recomeça o mesmo passo 5 do
zero. Três relançamentos seguidos não produziram um único passo novo.

Uma sessão do `greedy_nat` leva 5 a 7 minutos e **cabe**.

**A adaptação.** O programa passa a rodar `greedy_nat` até o fim primeiro, e só
depois o `full`. Rodar o braço cuja unidade cabe é o que transforma capacidade
instável em dado commitado; a alternativa era não produzir nada.

**O que isso custa, dito com todas as letras.** Os dois braços passam a ser
medidos em janelas de tempo diferentes, então deriva de máquina vira um
confundidor possível — exatamente o que a regra de intercalar existe para
impedir. Duas coisas limitam o estrago, e nenhuma delas o elimina:

1. O ganho é razão contra o **seed da própria semente**, medido na mesma máquina
   no mesmo instante. Deriva multiplicativa cancela em primeira ordem.
2. A análise reporta a deriva medida entre janelas, pelos seeds. Se ela for da
   ordem da diferença entre braços, a comparação está comprometida e o relatório
   dirá isso.

Já se sabe que a deriva aqui **não é pequena**: os seeds do `sql_agg` foram
medidos entre 1,63 e 2,46 no mesmo dia — 47% de variação, provavelmente estado de
page cache. Isso é grande o bastante para exigir a checagem, não para presumir
que invalidou.

**O que seria melhor e não está disponível.** Rodar os dois braços intercalados
numa máquina estável. Se este experimento for repetido em infraestrutura que não
recicle containers, é assim que deve ser feito, e este parágrafo é a instrução.

---

## 8. Propriedade observada em execução: metade dos passos do `full` é truncada

Nas três primeiras sementes, **12 dos 24 passos do `full` foram mortos pelo
timeout de 20 minutos**:

| semente | passos | mortos | aceitos | duração média |
|---|---|---|---|---|
| s0 | 8 | 4 | 4 | 1 033 s |
| s1 | 8 | 2 | 2 | 916 s |
| s2 | 8 | **6** | 3 | 1 135 s |

O piloto já apontava para isso — os passos usavam ~1 080 s de um teto de 1 200 —
mas ali nenhum foi morto. Em execução, o agente encosta no teto na metade das
vezes.

**Duas consequências, e nenhuma invalida a comparação.**

O custo medido **subestima**. Um passo morto não emite o evento `result`, então
volta sem `total_cost_usd`. O `full` s2 aparece com US$ 7,68 e gastou perto de
US$ 42 pela taxa observada de US$ 0,0048/s. A análise já imputa isso e marca
quantos pontos foram imputados; sem a imputação, o braço caro pareceria barato
exatamente nas sementes em que mais gastou. **A estimativa de custo da Fase 2A
sobe de ~US$ 233 para ~US$ 440.**

Um passo morto **não é um passo perdido**. O harness avalia a árvore de trabalho
depois de matar o agente, e o que estiver lá conta: os passos 1 e 3 do s2 foram
mortos e mesmo assim **aceitos**. O agente escreve enquanto trabalha, e o gate
julga o que ele deixou.

**O que isto diz sobre o braço.** O `full` desta configuração é "o agente tem 20
minutos por passo, e metade das vezes isso não basta". É uma escolha de desenho
declarada, constante entre sementes, e portanto comparável — mas quem repetir
este experimento deve saber que um teto maior é outro braço, provavelmente
melhor, e que medir os dois seria a pergunta seguinte.

Não aumento o teto agora por duas razões: mudaria o braço no meio de um
experimento pré-registrado, e passos mais longos são piores sob a reciclagem de
container descrita em §7 — um passo de 30 minutos quase nunca fecharia.

---

## 9. Regra de extensão, fixada com o `full` em n=5

Escrita **antes** de o braço fechar, e o commit prova. Existe porque o
dimensionamento de §4 usou o desvio do `greedy` como estimativa — 0,193 — e o
desvio do `full` saiu maior.

**O que já se sabe com n=5 do `full` e n=11 do `greedy`:**

| braço | n | média | desvio |
|---|---|---|---|
| `greedy_nat` | 11 | 4,574 | 0,158 |
| `full` | 5 | 4,788 | **0,330** |

Diferença observada: **+0,214** (4,7%), a favor do `full`. Desvio combinado:
0,221. MDE deste desenho a n=11 por braço: **0,264** — maior que o efeito. O
experimento pré-registrado **não vai distinguir** a diferença que está medindo,
e isso já é previsível agora, não depois.

O erro foi assumir que o desvio do braço barato serviria para o caro. §4 até
disse que isso era "conservador" porque o gate truncaria a amostra ruim — a
mesma hipótese que o `csv_normalize` sugeriu e que aqui o dado nega: o `full`
espalha **duas vezes** mais que o `greedy`, não menos.

**A regra, fixada agora:**

1. A Fase 2A vai até n=11 por braço, como pré-registrado. Essa análise é a
   principal e sai completa, com o MDE e o n necessário.
2. **Se** o p ajustado por Holm ficar acima de 0,05 **e** a diferença observada
   ficar abaixo do MDE, os dois braços são estendidos até **n=17** — o n que o
   desvio combinado observado implica para o efeito observado, por
   `n ≈ 2·(2,8·s/Δ)²`.
3. O relatório publica **as duas análises**, n=11 e n=17, com a extensão
   marcada. A de n=11 é confirmatória; a de n=17 é a mesma pergunta com poder
   adequado, e o fato de o n ter sido escolhido depois de ver o desvio fica
   escrito nela.
4. O critério de parada é o n, nunca o p. Não há "estender até dar
   significativo": 17 é calculado agora, do desvio de agora, e não se move
   depois.

**Custo da extensão:** 6 sementes do `full` a ~US$ 40 e 2,4 h cada, mais 6 do
`greedy` a US$ 2,26 — **~US$ 254 e ~15 h**. Dentro do teto autorizado.

A alternativa era publicar um experimento subdimensionado sabendo que estava
subdimensionado. Estender com a regra escrita antes é melhor ciência; estender
depois de olhar o p seria pior que não estender.

---

## 10. RESULTADO

**n=11 por braço, esforço igualado em `xhigh`, medição pareada.**

| braço | n | ganho | desvio | US$/semente | relógio |
|---|---|---|---|---|---|
| `greedy_nat` — uma sessão | 11 | **4,606** | 0,184 | ~6 | 27 min |
| `full` — 8 passos, gate, lineage, supervisor | 11 | **4,633** | 0,188 | ~40 | 2,4 h |

| | |
|---|---|
| diferença | **+0,026× (+0,57%)**, a favor do `full` |
| IC95 (bootstrap, 10 000) | **[−0,125, +0,170]** — contém zero |
| p (permutação bilateral) | **0,748** |
| MDE com n=11 | 0,222 |
| **n necessário para distinguir** | **786 por braço** (~US$ 36 000) |

**A estrutura do AVO custa 7× mais dinheiro e 5× mais relógio para entregar 0,6%
a mais — e 0,6% é oito vezes menor que o menor efeito que este desenho consegue
enxergar.**

### A medição pareada foi o que produziu este número

Os valores brutos diziam outra coisa: `full` 4,955 ± 0,609 contra `greedy`
4,719 ± 0,178, uma diferença de **+5,0%**. Era artefato.

O ganho é `final / seed`, e os dois são medidos com até 2,4 h de distância. O
braço `full` rodou ao longo de dois dias, com seeds medidos entre 1,59 e 2,41; o
`greedy` rodou num bloco, com seeds entre 2,14 e 2,25. As quatro sementes do
`full` cujo seed caiu ~28% abaixo da mediana produziram os quatro maiores ganhos
do braço.

`remedir.py` mede o seed e o artefato final de cada run um atrás do outro, na
mesma máquina, depois que tudo acabou. O efeito:

| | bruto | pareado |
|---|---|---|
| `full` | 4,955 ± 0,609 | 4,633 ± **0,188** |
| `greedy` | 4,719 ± 0,178 | 4,606 ± 0,184 |
| diferença | +0,235× | **+0,026×** |
| amplitude dos seeds | 52% | **8,4%** |

O caso mais claro é a semente `full` s8: seed 1,600 → 2,189, ganho **6,68× →
4,77×**. O melhor resultado do experimento inteiro era deriva de máquina.

E note o desvio: o `full` parecia espalhar 3,3× mais que o `greedy` (0,609
contra 0,178). Pareado, os dois espalham igual (0,188 e 0,184). **A hipótese de
que o gate compra confiabilidade — que eu levantei no `csv_normalize` e marquei
como exploratória — não sobrevive: não havia variância extra para o gate
reduzir, havia deriva de máquina no meu instrumento.**

### A regra de extensão de §9 fica sem premissa

§9 mandava estender para n=17 se o efeito ficasse abaixo do MDE, e 17 era o n
implicado por uma diferença de 0,214 com desvio 0,221. A medição pareada mudou a
diferença para 0,026 e o desvio para 0,186. O n implicado agora é **786**, e n=17
detectaria 0,178 — ainda sete vezes maior que o efeito real.

Executar a extensão seria gastar US$ 254 para deixar de detectar algo que já se
sabe indetectável nessa faixa de orçamento. A regra não é abandonada: ela é
aplicada, e o n que ela produz com os dados corretos é 786. Isso está escrito
aqui em vez de a extensão ser silenciosamente pulada.

### O que este resultado é, e o que não é

**É:** no `sql_agg`, com esforço igualado e deriva removida, o laço evolutivo
completo do AVO — lineage, gate com reversão, memória entre passos, supervisor —
não se distingue de uma única sessão do mesmo modelo com o mesmo avaliador na
mão. A US$ 40 contra US$ 6.

**Não é:** evidência de que a arquitetura do AVO não funciona. O regime do paper
são sete dias contínuos e centenas de iterações num espaço que nenhuma sessão
esgota. Aqui, oito passos num alvo cujo teto uma sessão de 27 minutos alcança.
Um resultado nulo nesta escala é uma afirmação sobre **esta escala**.

**Também não é** "empate". É uma diferença medida de +0,57% com intervalo
[−0,125, +0,170]. A afirmação honesta é: *se houver vantagem, ela é menor que
3,7% do ganho, que é o limite superior do intervalo.*
