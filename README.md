# AVO Data Lab

Bancada para reproduzir e **ablacionar** a arquitetura AVO (NVIDIA,
arXiv:2603.24517) em tarefas de engenharia de dados — Python, SQL, normalização
e record linkage.

O harness da busca evolutiva é o upstream `gatordevin/avo`, fixado por commit em
`vendor/avo.lock`. **O que é nosso são os alvos, o gate, a disciplina que os
verifica e o experimento que eles servem.**

## Começar

```bash
make setup                  # clona o harness no commit fixado, instala, gera datasets, verifica
make verify                 # lint + testes + gate de todos os alvos + dimensionamento
make run TARGET=etl_agg     # abre um run e imprime o primeiro prompt de variação
```

Depois abra `docs/RUNBOOK.md` e cole a Sessão 0 numa sessão do Claude Code.

O modo padrão é **modo sessão**: o harness entrega o prompt de variação para a
conversa corrente, sem spawnar agente e sem chamar API. Custo marginal zero. O
modo não supervisionado existe e gasta quota — é opt-in de propósito.

## Os alvos

| alvo | domínio | `f` maximiza | mutantes | headroom medido | custo do seed |
|---|---|---|---|---|---|
| `etl_agg` | agregação de transações (JSONL → dict) | throughput, geomean de 3 formas de dado | 9 | 3,4× em 3 passos | 3,0s |
| `csv_normalize` | normalização de cadastro sujo (CSV → canônico) | throughput sob correção exata | 18 | 4,7× em 6 passos | 5,0s |
| `sql_agg` | consulta analítica sobre SQLite congelado | throughput, frio vs quente | 21 | 4,3× em 7 degraus | 8,0s |
| `dedupe_match` | record linkage / deduplicação | **F1** sob orçamento de tempo | 13 | 3,6× em 7 versões | 9,3s |

O headroom não é estimativa: para cada alvo foram escritas e medidas versões
progressivamente melhores pelo avaliador de verdade, e no `csv_normalize` a
escada foi reproduzida de forma independente numa auditoria (4,7× contra os 5,1×
do autor — a diferença é ruído de máquina, e ambos ficam na faixa). Nenhum
movimento isolado vale mais de 46% do ganho, que é a propriedade que permite a
uma ablação distinguir braços. `make verify` confere os quatro.

Os três primeiros maximizam velocidade; o quarto maximiza **qualidade** sob um
orçamento de tempo. Isso é deliberado: a tese central do paper (C14) é que "o
agente subjacente permanece o mesmo; apenas as ferramentas e a avaliação mudam".
Um alvo cuja métrica tem forma diferente é o teste dessa tese dentro da própria
bancada — e o gate do `dedupe_match` precisa provar coisas que os outros não
precisam, como que o candidato **não leu o gabarito**.

## O que tem aqui

| caminho | o quê |
|---|---|
| `targets/` | os alvos: seed `x_0`, knowledge base `K`, e `eval.py` (a função `f`) |
| `labkit/` | a biblioteca compartilhada: medição, gate, mutantes, datasets congelados |
| `tests/` | a suíte que recusa alvo sem gate — cada falha histórica virou regressão |
| `docs/TARGET_DESIGN.md` | **leia antes de criar um alvo.** As quatro propriedades de um alvo válido |
| `docs/ABLATION_PROTOCOL.md` | o experimento científico, pré-registrado |
| `docs/AVO_REPLICATION_REPORT.md` | evidence ledger: o que é NVIDIA vs. reprodução aberta |
| `docs/PLANO_AVO_DATA_ENGINEERING.md` | os tiers e o histórico do que já quebrou |
| `docs/RUNBOOK.md` | prompts prontos, por sessão, com critério de parada |
| `CLAUDE.md` | regras operacionais para o agente |
| `examples/etl_agg-run/` | um run real: lineage, a rejeição pelo gate, e as notas de trabalho |
| `.claude/` | permissões e os hooks que tornam as regras invioláveis mecânicas |

## Como isso se parece rodando

Um run real de quatro passos no `etl_agg`, em `examples/etl_agg-run/`. Nenhum
número abaixo foi escrito à mão:

| ver | primary | Δ | aceito | o que mudou |
|---|---|---|---|---|
| 0 | 4,163 | — | seed | materializa tudo, reagrupa, 4 travessias por grupo |
| 1 | 6,877 | +65,2% | ✅ | passe único com acumulador em lista |
| 2 | 10,275 | +49,4% | ✅ | extração dirigida dos 5 campos de 16 |
| — | 0 | — | ❌ | arredondamento durante a acumulação — **rejeitado pelo gate** |
| 3 | 14,009 | +36,3% | ✅ | busca inline no lugar da auxiliar por campo |

Três movimentos independentes, retornos decrescentes, nenhum capturando mais de
38% do ganho acumulado. É a forma que um alvo precisa ter para servir a uma
ablação — e é o que a versão anterior deste alvo não tinha.

A rejeição merece atenção. O gate disse:

```
ACC00000|BRL.gross: soma verdadeira 21424.216176, obtido 21424.23
(erro 0.0138 > tolerância 0.0050). Arredondar durante a acumulação em vez
de no final produz exatamente este desvio.
```

É exatamente a mudança que a versão antiga do gate **aceitou como correta**.

## A regra que importa

O loop pode rodar sem você. **A definição de `f` não.** Quando `f` está errado, o
agente não trava — ele fica confiante, e cada versão seguinte é construída em
cima do erro.

Por isso todo alvo exige `--selftest` com mutantes que o gate **tem** que
rejeitar, `--budget` que confirma o dimensionamento, e um hook que bloqueia a
edição do árbitro. Não é zelo: é o resultado de ter escrito um gate que parecia
sólido, tentado quebrá-lo de propósito, e conseguido.

## As cinco falhas que este repositório existe para não repetir

Todas aconteceram de verdade. Todas viraram verificação automática.

1. **Gate fraco.** O mesmo dataset media tempo e julgava correção. Um candidato
   que arredondava a cada acumulação — violando o contrato — **passou no gate**;
   só foi rejeitado por ser mais lento. Um dataset com duas casas decimais é
   estruturalmente incapaz de expor esse erro.
   → Datasets separados, gate adversarial, ≥ 5 mutantes obrigatórios,
   e um gerador que se recusa a escrever dataset de gate sem mordida.

2. **Custo de avaliação.** O seed levava 93 s por execução: 7,8 min por
   avaliação, 65 h só de medição para as 500+ direções do paper. Dimensionamos
   pelo candidato otimizado em vez de pelo seed.
   → `--budget` verifica teto (seed ≤ 25 s) e piso (execução ≥ 20 ms).

3. **`avo submit` é sensível ao diretório.** Falha se rodado de dentro do run
   dir; precisa ser da raiz com `--run`.
   → Documentado em `CLAUDE.md` e embrulhado num alvo do Makefile.

4. **Headroom concentrado.** Corrigir a falha 2 revelou a pior das quatro: o
   primeiro movimento óbvio capturava 98% do ganho disponível (57,8× de 132×).
   Um alvo assim **não consegue distinguir braços de uma ablação** — todos
   encontram o mesmo ganho no passo 1 e estagnam juntos —, e a ablação é o motivo
   de a bancada existir.
   → Regra: 3×–8× de headroom em ≥ 4 movimentos, nenhum valendo > 70%.

5. **Medição trapaceável.** Achada atacando o `etl_agg` depois de dá-lo por
   pronto, com `--selftest` verde. Um candidato que memoiza a saída indexada
   pelo caminho marcou **4.672.896** contra 4,16 do seed — um milhão de vezes
   "melhor", sem uma única otimização. Nenhum gate de correção pega isso: o
   resultado devolvido *está* certo.
   → Três camadas: caminho novo, módulo novo, e proibição de escrever em disco
   durante a medição. Depois delas, a memoização por conteúdo pontua **abaixo**
   da versão honesta e o cache em disco é reprovado por nome. Trapacear passou de
   valer um milhão a custar caro.

Duas são especialmente instrutivas. A quarta, porque um ganho de 57,8× parece um
sucesso retumbante do sistema e era o sintoma de um alvo mal projetado. A quinta,
porque cada correção expôs a seguinte — e a última só apareceu porque alguém
tentou trapacear de propósito num alvo que já estava "pronto".

## Por que ablação, e não mais um benchmark

A NVIDIA publicou uma arquitetura com cinco componentes, destacou dois como
"particularmente importantes", e **declarou por escrito que não mediu a
contribuição individual de nenhum**. Ninguém publicou essa ablação — nem a
reprodução aberta, nem VISTA, nem Tycho.

Enquanto isso, reproduzir 100% no public set do ARC-AGI-3 deixou de ser
resultado: três sistemas independentes já o saturaram. E o "30% → 100%" que
circulou na imprensa vem do subtítulo do post da NVIDIA, cujo próprio corpo diz
que os números "não devem ser interpretados como medida direta da contribuição
de performance do AVO".

O detalhamento — o que é confirmado, o que é inferido, e o que é escolha da
reprodução aberta — está em `docs/AVO_REPLICATION_REPORT.md`, linha a linha.

## Licença

MIT. O harness upstream tem licença própria e não é redistribuído aqui: o
`bootstrap.sh` o clona no commit fixado.
