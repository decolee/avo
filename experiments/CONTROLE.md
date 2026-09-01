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
