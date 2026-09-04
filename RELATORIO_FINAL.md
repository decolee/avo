# AVO Data Lab — relatório final

**A pergunta:** a arquitetura de busca evolutiva da NVIDIA (AVO, arXiv:2603.24517)
entrega ganho além do que o mesmo modelo entrega sozinho?

**A resposta, medida:** neste alvo e nesta escala, **não de forma detectável**.
Com esforço igualado e deriva de medição removida, o laço completo — lineage,
gate com reversão automática, memória entre passos, supervisor — mede **4,633×**
contra **4,606×** de uma única sessão do mesmo modelo com o mesmo avaliador na
mão. Diferença de **0,57%**, com intervalo de confiança que contém zero, por
**4,4× mais dinheiro e 4,5× mais relógio**.

---

## 1. O resultado

`sql_agg` (otimização de consulta SQLite sob igualdade exata de result set),
n=11 por braço, `--effort xhigh` nos dois, medição pareada.

| braço | ganho | desvio | US$/semente | agente |
|---|---|---|---|---|
| `greedy` — uma sessão, sem estrutura | **4,606** | 0,184 | 8,39 | 30 min |
| `full` — 8 passos do AVO completo | **4,633** | 0,188 | 36,95 | 136 min |

| estatística | valor |
|---|---|
| diferença | **+0,026× (+0,57%)** |
| IC95 (bootstrap, 10 000 reamostragens) | **[−0,125, +0,170]** |
| p (permutação bilateral) | **0,748** |
| efeito mínimo detectável com n=11 | 0,222 |
| **n necessário para distinguir** | **786 por braço (~US$ 36 000)** |

**A afirmação honesta:** se existe vantagem da estrutura, ela é **menor que 3,7%
do ganho** — o limite superior do intervalo. Não é "empate": é uma diferença
medida, pequena, com incerteza quantificada.

O que o laço fez, em números: 88 passos de agente, **40% aceitos**, **40% mortos
pelo timeout de 20 min** (e um passo morto ainda pode ser aceito — o harness
avalia a árvore depois de matar o agente). O supervisor disparou **26 vezes**, a
primeira vez que ele dispara neste laboratório. **22 de 22 runs terminaram
corretos** sob o gate adversarial.

## 2. O número só apareceu depois de consertar o instrumento

Os valores brutos diziam **+5,0%** a favor do `full`. Eram artefato.

O ganho é `final / seed`, e as duas medidas ficam até 2,4 h separadas. O braço
`full` rodou ao longo de dois dias, com seeds medidos entre 1,59 e 2,41; o
`greedy` rodou num bloco de 5 h, com seeds entre 2,14 e 2,25. **As quatro
sementes do `full` cujo seed caiu ~28% abaixo da mediana produziram os quatro
maiores ganhos do braço.**

`experiments/ablacao/remedir.py` mede o seed e o artefato final de cada run um
atrás do outro, na mesma máquina, depois que tudo acabou:

| | bruto | pareado |
|---|---|---|
| `full` | 4,955 ± 0,609 | 4,633 ± **0,188** |
| `greedy` | 4,719 ± 0,178 | 4,606 ± 0,184 |
| **diferença** | **+0,235×** | **+0,026×** |
| amplitude dos seeds | 52% | **8,4%** |

O caso mais claro é a semente `full` s8: seed 1,600 → 2,189, ganho **6,68× →
4,77×**. O melhor resultado do experimento inteiro era deriva de máquina.

E note o desvio: o `full` parecia espalhar **3,3× mais** que o `greedy`. Pareado,
os dois espalham igual. **A hipótese de que o gate compra confiabilidade — que
levantei no `csv_normalize` e marquei como exploratória — não sobrevive. Não
havia variância extra para o gate reduzir; havia deriva no instrumento.**

## 3. O que o laboratório encontrou em si mesmo

Esta é, honestamente, a contribuição maior. Oito defeitos, todos encontrados
depois de o alvo ou o experimento ser dado por pronto, cada um agora com
verificação automática.

| # | defeito | como se descobriu | conserto verificável |
|---|---|---|---|
| 1 | gate cego a arredondamento incremental | candidato errado passou | datasets separados, ≥5 mutantes, gerador recusa gate sem mordida |
| 2 | custo de avaliação mal dimensionado (93 s/execução) | `--budget` | teto de 25 s no seed, piso de 20 ms por execução |
| 3 | `avo submit` sensível ao diretório | falhou em uso | documentado, embrulhado no Makefile |
| 4 | headroom concentrado (98% num movimento) | ao corrigir #2 | barra de 3× em ≥4 movimentos, cobrada pelo `verify` |
| 5 | medição trapaceável (memoização marcou 4 672 896×) | ataque deliberado ao próprio alvo | caminho novo + módulo novo + proibição de escrita em disco |
| 6 | gate e benchmark compartilhando ordem de campos | busca real explorou | gerador do gate permuta chaves; 4 de 5 versões de um lineage reprovaram |
| 7 | teto do alvo alcançável numa sessão | usar o alvo para comparar arquiteturas | sonda de 100 s, cobrada pelo `verify` |
| 8 | **agentes não conseguiam medir** | ler o que os agentes escreveram | `--allowed-tools`; análise aborta se alguma sessão for cega |

O oitavo é o mais sério e o mais instrutivo. `--permission-mode acceptEdits`
libera edição de arquivo e **exige aprovação para Bash**, que nunca vem num run
não supervisionado. **54 de 81 sessões de agente (67%) terminaram sem conseguir
medir uma única vez** — inclusive 15 dos 21 passos do braço `full`. Os runs
terminavam com exit 0, score positivo, correção verificada e commits aceitos.
Nada estava vermelho. Só apareceu ao ler o texto que os agentes escreveram sobre
a própria sessão: *"medi ZERO ideias porque o avaliador foi recusado por
permissão"*.

E mais quatro defeitos de execução, encontrados durante a Fase 2A:

- **dois programas rodando em paralelo por 1,5 h** — um `pkill` com âncora não
  casou o processo antigo. Onze sessões do `greedy` foram medidas com um agente
  do `full` disputando CPU. Conserto: `flock`, testado com dois processos reais.
- **esforço diferente entre braços desde sempre** — o comando que cria o run
  nunca passou `--effort`, então o harness usava o default dele (`xhigh`)
  enquanto o `greedy` passava `medium`. O parâmetro existia na assinatura e era
  código morto. O desequilíbrio favorecia o `full`.
- **seed corrompido em run retomado** — a retomada lia o baseline da última
  linha do `scores.jsonl`, que num run retomado é o melhor score já conquistado.
  Uma semente registrou ganho 1,00× quando o real era 4,47×.
- **custo pela metade em run retomado** — a linha registrava só os passos da
  última invocação: US$ 9,04 em vez de US$ 21,75.

Nenhum desses apareceria numa métrica. Todos apareceram ao desconfiar de um
número que parecia bom demais ou ruim demais.

## 4. Recomendação: **não** rodar as Fases 2B e 3 como desenhadas

**Fase 2B** (`greedy_cont`, retomado até igualar os 136 min do `full`, ~US$ 760)
existia para fechar a porta do *"o `full` só ganhou porque teve mais compute"*.
**O `full` não ganhou.** A porta não precisa ser fechada.

**Fase 3** (ablação de componentes: sem KB, sem memória, sem supervisor, ~US$ 380)
mede a contribuição de cada peça de uma estrutura cuja contribuição total é
**0,57% e indistinguível de zero**. Uma peça dela seria uma fração disso. Com o
desvio observado, distinguir a estrutura inteira pede 786 sementes por braço;
distinguir uma peça pede mais. Rodar seria comprar de novo o mesmo intervalo que
contém zero — o erro que este laboratório já cometeu duas vezes, por US$ 343.

**O que fazer com os US$ 1 100 economizados, em ordem de valor:**

1. **Construir um alvo cujo espaço uma sessão não esgote.** É o gargalo real, e
   é a nona propriedade que o `TARGET_DESIGN.md` ainda não tem. Nos cinco alvos
   atuais, uma sessão de 100 s captura de 46% a 254% do headroom declarado. O
   regime do paper — sete dias, centenas de iterações — só existe onde a busca
   não termina em meia hora. Candidatos: um alvo com muitos eixos independentes
   de otimização, onde o ganho exija combinar dezenas de movimentos que não
   cabem num contexto.

2. **Repetir a Fase 2A intercalada, em máquina estável.** O desvio pareado é
   0,186; num ambiente sem reciclagem de container dá para intercalar os braços
   de verdade e eliminar a deriva no desenho em vez de na análise. Custo similar,
   validade maior.

3. **Levar o método para o Postgres de vocês.** O que transfere não são os
   números — 4,6× em SQLite não prevê nada sobre a produção — é a receita:
   dataset congelado com lock, gate adversarial separado do benchmark, sonda de
   §3e, piloto de potência antes de gastar. Esse é o degrau 3 do
   `PLANO_AVO_DATA_ENGINEERING.md`, e o trabalho difícil ali é de engenharia de
   dados: um `f` que meça custo real de forma reprodutível sem tocar produção.

**O que eu não recomendo:** aumentar n na Fase 2A. A regra de extensão que
pré-registrei (§9 de `FASE2_SQL_AGG.md`) mandava ir a n=17 se o efeito ficasse
abaixo do MDE. Com os dados corrigidos, o n implicado é 786 — n=17 detectaria
0,178, ainda sete vezes o efeito real. A regra foi aplicada, não pulada; o n que
ela produz é inviável, e isso está escrito.

## 5. O que ficou no repositório

```
labkit/            evalkit, datakit, contracts, cli — a espinha medida
targets/           5 alvos, 73 mutantes somados, datasets com lock SHA256
experiments/       runners, análise, sonda, piloto, re-medição, orquestrador
docs/              TARGET_DESIGN (9 propriedades), ABLATION_PROTOCOL,
                   AVO_REPLICATION_REPORT (ledger com 17 itens confirmados)
```

- **137 testes verdes**, 4 skipped declarados.
- **`avo-lab verify`** cobra as nove propriedades e hoje aprova **1 de 5** alvos
  para ablação — o `sql_agg`. Isso é o repositório reprovando a si mesmo por
  medida, não por prosa.
- **Dados brutos preservados**, inclusive os inválidos, com um `LEIA.md`
  explicando por que cada lote foi descartado: `CONTAMINADO/` (execução
  concorrente), `CONFUNDIDO_EFFORT/` (esforço desigual), `piloto_sql_agg_CEGO/`
  (agentes sem avaliador), `invalidas/` (API 529).

## 6. Custo

**~US$ 980 identificáveis** em custo de agente, ao longo de sete experimentos.
Cerca de **US$ 380 foram gastos em dados que precisaram ser descartados** por
defeitos do próprio laboratório — e descobrir cada um deles é o que torna os
US$ 600 restantes confiáveis.

---

## Apêndice: o que este relatório NÃO afirma

**Não afirma que o AVO da NVIDIA não funciona.** O regime deles são sete dias
contínuos em B200, 500+ direções exploradas, 40 versões commitadas, contra um
kernel que já era estado da arte. Aqui são oito passos num alvo cujo teto uma
sessão de 27 minutos alcança. Um resultado nulo nesta escala é uma afirmação
sobre **esta escala**.

**Não afirma que o modelo melhorou.** O AVO não treina nada; os pesos não mudam.
O que melhora é o artefato — a consulta SQL, o normalizador. O Opus que começa o
passo 8 é o mesmo que começou o passo 1.

**Não afirma nada sobre o supervisor, a KB ou a memória isoladamente.** Essa era
a Fase 3, e a recomendação é não rodá-la até existir um alvo onde a estrutura
inteira mostre efeito.

**Afirma, com número:** que a diferença entre a máquina completa e o modelo
sozinho, neste alvo, é 0,57% com IC95 [−0,125, +0,170]; que distingui-la custaria
US$ 36 000; e que 5,0% da diferença que os dados brutos mostravam era deriva do
instrumento, não da arquitetura.
