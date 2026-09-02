# Controle honesto: `full` contra `greedy`

**Estado: rodando.** Este documento foi escrito *antes* dos dados do `greedy`
existirem, e a análise (`experiments/ablacao/analise_controle.py`) foi commitada
antes da primeira linha de `resultados/greedy.jsonl`. O histórico do git prova as
duas coisas. É o cegamento que `docs/ABLATION_PROTOCOL.md` §4 exige, na forma
mais forte que dá para ter com um experimentador só: o método não pode ter sido
escolhido depois de ver o resultado porque ele é anterior ao resultado.

## 1. A pergunta

`docs/ABLATION_PROTOCOL.md` §1 pergunta quanto do ganho do AVO vem da estrutura
— lineage, gate, memória, supervisão — e quanto vem do modelo. A ablação de
componentes (Sessão 3) responde à segunda metade: qual peça contribui. Ela não
responde à primeira, e a primeira vem antes:

> **A estrutura contribui alguma coisa?**

Se o mesmo modelo, com o mesmo seed, a mesma KB e o mesmo avaliador na mão,
chega ao mesmo lugar numa sessão só, então a arquitetura é overhead e medir a
contribuição das peças dela é medir variação de uma coisa que não faz diferença.

## 2. Por que a comparação é entre curvas, não entre pontos

O desenho original comparava um ponto: `full` no fim contra `greedy` no fim. Dois
números do próprio laboratório o inviabilizam.

O `full`, em três passos no `csv_normalize`, gasta **2471s de agente e US$ 11,58**
para chegar a **4,91×**. Mas ele já estava em **4,44× depois do primeiro passo**,
com 1086s. Os outros dois passos compraram 0,47× com 1385s a mais.

Do outro lado, o smoke test do plumbing — uma sessão de `greedy` morta por
timeout aos **100 segundos** — mediu **3,90×**.

A curva é quase plana entre 100s e 2471s. Comparar só os pontos finais compara a
parte plana dela: qualquer diferença real cabe dentro do ruído, e a conclusão
"empate" seria uma afirmação sobre a resolução do experimento disfarçada de
afirmação sobre a arquitetura.

Então mede-se a curva inteira, **pareada por compute**. Do lado do `full` ela sai
de graça: cada semente registra o score depois de cada passo e o tempo de agente
acumulado até ali. Do lado do `greedy`, cada ponto é uma sessão nova com
orçamento declarado.

Cada ponto do `greedy` é uma sessão com o próprio orçamento, e não um retrato de
uma sessão longa aos X segundos. A diferença importa: um agente que sabe que tem
10 minutos planeja diferente de um que sabe que tem 40. É o comportamento sob
orçamento que se compara ao `full` sob k passos, porque o `full` também sabe que
o passo dele tem um teto.

## 3. Os braços

| braço | orçamento | instrução de parada |
|---|---|---|
| `full` | 3 passos, ~2471s de agente | o harness decide |
| `greedy_nat` | teto igual ao do `full` | livre para parar quando quiser |
| `greedy_b100` | 100s | gaste o orçamento |
| `greedy_b600` | 600s | gaste o orçamento |
| `greedy_b1200` | 1200s | gaste o orçamento |
| `greedy_bmax` | ~2471s, pareado ao `full` | gaste o orçamento |
| `greedy_cont` | ~2471s, pareado ao `full` | **retomada mecânica** até o orçamento acabar (§3b) |

Os dois perfis de `greedy` existem porque cada um sozinho seria criticável.

O **natural** é o comportamento default: a calibração mostrou que ele para
sozinho perto dos 700s, com US$ 3,98. É o que um engenheiro obtém ao pedir
"otimize isso". Comparado sozinho contra o `full`, daria ao `full` três vezes
mais compute, e a crítica seria justa.

O **persistente** recebe a instrução de gastar o orçamento inteiro, tentar pelo
menos três ideias distintas antes de declarar esgotamento, e **guardar a melhor
versão que mediu**. Essa última cláusula é deliberada: sem gate persistente, uma
regressão não é desfeita por ninguém, e deixar o `greedy` terminar numa
regressão que ele mesmo poderia ter desfeito seria construir um espantalho. O
controle tem que ser a versão mais forte de "sem estrutura", não a mais fraca.

O que o `greedy` **recebe**, igual ao `full`: o mesmo seed, a mesma KB, o mesmo
avaliador (chamável à vontade), o mesmo objetivo copiado do `target.yaml`, o
mesmo modelo, o mesmo `--effort`.

O que ele **não recebe** — e é exatamente a estrutura do AVO: lineage, gate
persistente com reversão automática, supervisor, e memória entre passos.

## 3b. Desvio declarado: o braço `greedy_cont` foi adicionado DEPOIS

Este braço não estava no pré-registro. Ele foi acrescentado depois da rodada 0, e
o commit que o cria é posterior aos dados que o motivaram. Declarar isso é
obrigatório: um experimento em que braços aparecem depois dos dados é um
experimento em que o desenho pode ter sido escolhido pelo resultado.

**O que a rodada 0 mostrou.** A instrução de persistir não segura o agente:

| braço | orçamento | gastou de fato |
|---|---|---|
| `greedy_b600` | 600 s | 405 s |
| `greedy_b1200` | 1200 s | 606 s |
| `greedy_bmax` | 2471 s | **731 s** |

Mandado gastar 2471 segundos, ele para aos 731. `greedy_b1200` e `greedy_bmax`
não são dois pontos da curva: são o mesmo ponto comprado duas vezes. A curva do
`greedy` simplesmente não tem ponto acima de ~700s, e sem um a comparação com o
`full` a 2471s continuaria respondível com "o `full` teve três vezes mais
compute".

**Por que o desvio é defensável.** A direção dele importa. `greedy_cont` torna o
controle mais forte, não mais fraco: ele dá ao braço-contra mais compute, mais
persistência e a instrução explícita de guardar a melhor versão medida. Um desvio
que fortalece a hipótese nula é o oposto do que a pré-registração existe para
impedir. Se eu tivesse acrescentado um braço que enfraquece o `greedy`, ou que dá
mais alguma coisa ao `full`, a leitura correta seria descartar o experimento.

**O que ele não é.** A retomada é mecânica: a mesma conversa continua
(`--resume`), com uma mensagem de texto fixo que não comenta a trajetória, não
sugere direção e não diz se o que veio antes foi bom. Ela não é lineage (não há
histórico de versões com score), não é gate (nada reverte nada), não é supervisor
(ninguém julga o caminho) e não é memória entre passos (não há passos). É a
recusa de parar cedo, e só.

**Como ler o resultado dele.** `greedy_cont` é confirmatório de nada: é n=4 num
braço escolhido depois dos dados. Se ele empatar com o `full`, a afirmação
honesta é "o controle mais forte que consegui montar empata dentro do MDE"; se
perder, é "empata até 700s e perde acima disso, num braço acrescentado post hoc".
Nenhuma das duas vira p-valor confirmatório. Os braços pré-registrados
(`greedy_nat`, `greedy_b100`, `greedy_b600`) continuam sendo a análise principal.

## 4. Sementes contemporâneas

Três sementes novas do `full` (s4–s6) rodam **intercaladas** com as do `greedy`,
na mesma janela. As quatro sementes que já existem foram medidas noutro dia, e
compará-las sozinhas contra o `greedy` deixaria "a máquina estava diferente" como
explicação alternativa de qualquer diferença.

A análise reporta a deriva entre as janelas explicitamente. O ganho é razão
contra o seed da própria semente, medido na mesma máquina no mesmo instante, o
que faz a deriva cancelar em primeira ordem — mas cancelar em primeira ordem não
é cancelar, e o número vai no relatório.

## 5. O que este experimento pode e não pode concluir

Pode: *"no orçamento X, a diferença entre `full` e `greedy` é D, com IC95 [a, b]"*.

Pode: *"a diferença é menor que o efeito mínimo detectável com este n"* — que é
uma afirmação sobre o experimento, e é honesta.

**Não pode**: *"não há diferença"*. Ausência de evidência não é evidência de
ausência, e com n desta ordem o intervalo é largo por construção.

**Não pode**: generalizar do `csv_normalize` para o AVO. Este é um alvo cujo
headroom de 5,1× um único agente alcança quase inteiro em 100 segundos. O regime
do paper é outro — centenas de iterações num espaço que nenhuma sessão esgota. Se
o resultado aqui for "empate", a leitura correta é *"nesta escala, neste alvo,
a estrutura não se paga"*, e a pergunta seguinte é qual alvo tem headroom que uma
sessão única não alcança. Não é *"o AVO não funciona"*.

## 6. Análise pré-registrada

Fixada em `analise_controle.py`, commitada antes dos dados:

- ganho = `primary_final / primary_seed`, sempre contra o seed da própria semente
- IC95 da diferença por **bootstrap** (10.000 reamostragens)
- p bilateral por **permutação**, sem suposição de distribuição
- **Holm-Bonferroni** sobre o conjunto de comparações
- **efeito mínimo detectável** reportado junto de toda diferença não significativa
- desbalanço de compute residual reportado em cada par
- taxa de agente morto por timeout, por braço
- `codigo_mudou`: uma sessão que falhou e não escreveu nada pode medir acima do
  seed por ruído; sem essa coluna isso vira "ganho"

---

## 7. Resultados

**24 execuções, ~11 h de relógio, ~US$ 175.** Sete sementes do `full` (quatro de
outro dia, três contemporâneas) e vinte e uma sessões do `greedy` em cinco
orçamentos. Alvo: `csv_normalize`. Sequencial do início ao fim.

### A curva

| braço | relógio | US$ | ganho | dp | n |
|---|---|---|---|---|---|
| `greedy_b100` | 106 s | 0,53 | 4,55× | 0,38 | 4 |
| `greedy_b600` | 283 s | 1,53 | 3,80× | 1,89 | 4 |
| `greedy_nat` | 527 s | 2,62 | 4,32× | 0,57 | 5 |
| `greedy_b1200` | 595 s | 2,78 | 5,33× | — | 1 |
| `greedy_bmax` | 634 s | 3,53 | 4,30× | 0,51 | 3 |
| `full` passo 1 | 1 060 s | 5,23 | 4,43× | 0,27 | 7 |
| `full` passo 2 | 1 680 s | 8,05 | 4,58× | 0,26 | 7 |
| **`full` passo 3** | **2 439 s** | **11,44** | **4,92×** | 0,39 | 7 |
| **`greedy_cont`** | **2 219 s** | **17,92** | **5,20×** | 0,75 | 4 |

### O resultado principal

**Nenhuma comparação é distinguível.** Todos os p ajustados por Holm deram
1,000. A comparação mais limpa — `greedy_cont` contra `full` no passo 3, com
apenas **+10% de desbalanço de relógio** — mede uma diferença de **−0,277×** (o
`greedy` à frente) com IC95 **[−0,983, +0,363]**. O intervalo contém zero com
folga dos dois lados.

Isso não é "empate". É o experimento dizendo que não tinha resolução:

| comparação | diferença | n por braço necessário |
|---|---|---|
| `greedy_cont` vs `full` p3 | −0,277× | ~59 |
| `greedy_b600` vs `full` p1 | +0,629× | ~49 |
| `greedy_b100` vs `full` p1 | −0,127× | ~92 |
| `greedy_bmax` vs `full` p1 | +0,127× | ~113 |
| `greedy_nat` vs `full` p1 | +0,105× | ~246 |

A ~US$ 15 por semente, resolver a comparação mais barata custaria **US$ 1.770**;
a mais cara, US$ 7.400. Por comparação.

### O número que explica todos os outros

Uma sessão de agente **morta aos 106 segundos**, custando **US$ 0,53**, mede
**4,55×**. O AVO completo, com **23× mais relógio** e **22× mais dinheiro**, mede
4,92×.

Medido sobre o ganho disponível — e não sobre o teto, porque um alvo de 6,2× tem
5,2× para distribuir — a sonda de cem segundos captura **68%**. Não sobra espaço
onde as arquiteturas possam diferir. Esta é a §3e de `docs/TARGET_DESIGN.md`, e
ela nasceu deste experimento.

### O que o `full` fez que o `greedy` não fez

Três coisas mensuráveis, nenhuma delas média:

**Ninguém desistiu.** Sete sementes do `full`, sete com código alterado. Quatro
passos individuais não mudaram nada — e o gate manteve a melhor versão e o passo
seguinte tentou de novo. No `greedy_b600`, uma semente em quatro terminou com o
arquivo intacto (6 avaliações, **0 edições**: o agente mediu e desistiu), e não
havia nada para obrigá-la a tentar de novo. Ela pontua 1,00×, e isso derruba a
média do braço de 4,73× para 3,80×.

**O `full` espalha menos.** Desvio de 0,26–0,39 contra 0,38–1,89 dos braços do
`greedy`. Há mecanismo — "iguala ou melhora" é literalmente um dispositivo de
redução de variância, porque trunca a amostra ruim em vez de commitá-la. Mas com
n de 3 a 5 o teste de dispersão não tem poder nenhum (p entre 0,33 e 0,96), e a
hipótese nasceu dos dados. É exploratória e está marcada como tal no relatório.

**O `greedy` não gasta o orçamento que recebe.** Mandado usar 2 471 s, para aos
731. Só a retomada mecânica (`greedy_cont`, §3b) o faz trabalhar de verdade: 44 a
62 avaliações e 20 a 40 edições por sessão, contra 10 a 15 e 2 a 9 dos outros
braços. Quatro vezes o trabalho empírico comprou 6% a mais de score — o que diz
mais sobre o teto do alvo do que sobre o agente.

### O preço da retomada

`greedy_cont` gasta **menos relógio e mais dinheiro** que o `full`: 2 219 s
contra 2 439 s, e US$ 17,92 contra US$ 11,44. Cada retomada reenvia o contexto
inteiro, então o custo por segundo salta de US$ 0,0047 para US$ 0,0081. Pareado
no relógio ele mede à frente; pareado no dólar, atrás. Um resultado que só
sobrevive num dos dois eixos é um resultado sobre o eixo, e o relatório faz os
dois pareamentos por isso.

### Deriva da máquina

O seed é o mesmo código medido em momentos diferentes, então o que varia nele é
ambiente puro: 2,365 na janela antiga contra 2,436 na nova, **+3,0%**. O ganho é
razão contra o seed da própria semente, medido na mesma máquina no mesmo
instante, então a deriva cancela em primeira ordem. Cancelar em primeira ordem
não é cancelar, e por isso as três sementes contemporâneas do `full` existem.

### O que este experimento NÃO mostrou

Não mostrou que a estrutura do AVO é inútil. Mostrou que **este alvo não a
testa**. Um alvo cujo espaço de busca uma sessão esgota em cem segundos está fora
do regime do paper por construção — lá são centenas de iterações num espaço que
nenhuma sessão esgota — e um resultado nulo nele é uma afirmação sobre o alvo.

O experimento custou US$ 175 para não distinguir nada. A sonda que teria contado
isso antes custa **US$ 0,50** e agora existe (`experiments/ablacao/sonda.py`),
é cobrada pelo `avo-lab verify`, e derrubou o `csv_normalize` de "apto para
ablação".
