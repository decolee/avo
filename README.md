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

| alvo | domínio | `f` maximiza | mutantes | headroom | apto p/ ablação |
|---|---|---|---|---|---|
| `csv_normalize` | normalização de cadastro sujo (CSV → canônico) | throughput sob correção exata | 18 | 5,10× / 6 passos | ✅ |
| `sql_agg` | consulta analítica sobre SQLite congelado | throughput, frio vs quente | 21 | 4,25× / 7 degraus | ✅ |
| `dedupe_match` | record linkage / deduplicação | **F1** sob orçamento de tempo | 13 | 3,55× / 7 versões | ✅ |
| `etl_agg` | agregação de transações (JSONL → dict) | throughput, geomean de 3 formas | 10 | 1,61× / 2 passos | ⚠️ |
| `sessionize` | sessionização de eventos (corte por intervalo) | throughput, 3 formas de tráfego | 11 | 1,83× / 3 passos | ⚠️ |

O headroom não é estimativa: para cada alvo foram escritas e medidas versões
progressivamente melhores pelo avaliador de verdade, o número está **declarado
no `target.yaml`**, e o `avo-lab verify` o cobra. No `csv_normalize` a escada foi
reproduzida de forma independente numa auditoria (4,7× contra 5,10× do autor — a
diferença é ruído de máquina, e ambos ficam na faixa).

Os dois marcados com ⚠️ são corretos, têm gate e estão dimensionados. Eles só não
alcançam a barra de 3× em 4 movimentos, e por isso não distinguem braços numa
ablação. O `verify` os reporta como **aviso, não erro**: tratar como falha de
build convidaria a afrouxar a barra; tratar como invisível deixaria a barra sem
efeito.

O caso do `etl_agg` merece nota. Ele era o alvo de referência do laboratório, com
3,6× de headroom — até a Sessão 2 endurecer o gate e mostrar que boa parte
daquele ganho vinha de uma suposição sobre a forma do arquivo. Sobrou 1,61×, e a
ablação teve de mudar de alvo por causa disso.

Quatro maximizam velocidade; o `dedupe_match` maximiza **qualidade** sob um
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

## As oito falhas que este repositório existe para não repetir

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

6. **Gate e benchmark compartilhando propriedades por acidente.** Achada rodando
   a busca de verdade (`experiments/REWARD_HACKING.md`). Como os dois datasets
   saem do mesmo gerador, tudo que eles compartilham sem querer — ordem dos
   campos, por exemplo — vira suposição livre para o candidato. Um extrator
   posicional media **+28,6%** sobre o melhor candidato honesto e passava.
   → O gerador do gate agora permuta a ordem das chaves. Ao endurecê-lo, **quatro
   das cinco versões de um lineage real passaram a reprovar** — cerca de 40% do
   ganho aparente era suposição, não otimização.

7. **O teto do alvo alcançável numa sessão.** Achada usando o alvo para aquilo
   que ele existia para fazer: comparar o AVO completo contra o mesmo modelo sem
   estrutura nenhuma (`experiments/CONTROLE.md`). Uma sessão de agente **morta
   aos 106 segundos**, custando **US$ 0,53**, mediu **4,55×** no
   `csv_normalize` — 68% de todo o ganho disponível. O AVO completo, com **23×
   mais relógio e 22× mais dinheiro**, mediu 4,92×. As duas medidas são
   indistinguíveis, e distinguir um efeito desse tamanho pediria de 49 a 246
   sementes por braço: de US$ 1.770 a US$ 7.400 por comparação.
   → A sonda dos 100 segundos (`experiments/ablacao/sonda.py`) mede isso por
   US$ 0,50, e o `avo-lab verify` passou a cobrá-la. Com ela ligada, **quatro
   dos seis alvos deste repositório deixam de ser aptos para ablação** — o
   `csv_normalize` inclusive, que era a referência.

8. **O agente não conseguia medir, e nada acusou.** Achada lendo os resumos das
   sessões — dois experimentos e US$ 343 tarde demais. O harness usa
   `bypassPermissions`, que é recusado quando o processo roda como root; ao
   trocar por `acceptEdits`, o Bash passou a exigir aprovação, e num run não
   supervisionado a aprovação não vem. Varrendo as transcrições dos dois
   experimentos, **54 de 81 sessões de agente (67%) terminaram sem conseguir
   medir uma única vez** — inclusive 15 dos 21 passos do braço `full`. E a
   cegueira foi **diferencial**: entre os braços do harness ela é uniforme
   (67–75%), mas do lado do `greedy` vai de 0% a 100%, e comparar um braço 71%
   cego contra outro 0% cego não mede arquitetura. O braço que eu escrevi
   explicitamente para *não* ser um espantalho — com um docstring dizendo que
   dar o avaliador a ele era deliberado — era um espantalho.
   → `--allowed-tools`, que torna a concessão explícita e idêntica em todos os
   braços. E `destilar_logs.py` correlaciona `tool_use` com `tool_result` por id
   e **sai com código 1 se qualquer sessão terminar cega**; a análise chama esse
   portão antes de qualquer estatística e **aborta** se ele não passar — correlacionar por id
   é o que importa, porque contar a *intenção* de chamar fazia as sessões cegas
   parecerem ter medido dezenas de vezes. Virou controle não negociável em
   `ABLATION_PROTOCOL.md` §4.

Cinco são especialmente instrutivas. A quarta, porque um ganho de 57,8× parece
um sucesso retumbante do sistema e era o sintoma de um alvo mal projetado. A
quinta, porque cada correção expôs a seguinte. A sexta, porque o alvo já tinha
nove mutantes, gate separado e três camadas anti-memoização — e mesmo assim não
distinguia "extrai por nome" de "extrai por posição", porque nunca tinha visto um
registro em outra ordem. A sétima, porque o alvo passava em **todas as outras
seis** e ainda assim não servia: headroom graduado diz que existem degraus, não
que subi-los exija mais de uma sessão. E a oitava, porque não é sobre projetar
alvos — é sobre **acreditar que um experimento mediu o que o desenho dizia**. As
sete primeiras foram achadas atacando o alvo; esta só apareceu ao ler o que os
agentes escreveram sobre a própria sessão.

## O que a ablação mostrou

Rodada em 2026-09-01: 4 braços × 4 sementes × 3 passos, modo não supervisionado
(um agente novo por passo, sem o conhecimento de quem escreveu os alvos).
12,2 h, US$ 168. Documento completo em `experiments/ABLATION.md`.

| braço | melhoria relativa | Δ vs `full` | distinguível? |
|---|---|---|---|
| `full` | 4,91 | — | — |
| `no_memory` | 5,26 | +0,35 | não |
| `no_supervisor` | 5,15 | +0,25 | não |
| `no_kb` | 5,10 | +0,19 | não |

**Nenhuma diferença é distinguível do ruído** (efeito mínimo detectável com n=4:
0,611; maior diferença observada: 0,350). Isso era previsível e estava
pré-registrado.

O resultado que vale mais é o defeito que o experimento encontrou **em si
mesmo**: com `stagnation_window=3` e runs de 3 passos, o supervisor **nunca
disparou** em 36 passos elegíveis. O braço `no_supervisor` executava exatamente o
mesmo código que o `full` — o que transforma a diferença entre eles numa medida
empírica do piso de ruído do desenho (~0,25), e invalida metade do experimento.

E o primeiro passo captura ~85% do ganho em todos os braços, que é justamente o
passo em que eles são mais parecidos. Três passos não medem arquitetura.

A §7 do documento tem as três correções e o preço de fazer direito: **US$ 840 e
~50 h**. Saber o custo antes de prometer a resposta também é resultado.

## O que o controle honesto mostrou

O experimento mais barato da §7 foi executado: `full` contra o **mesmo modelo sem
estrutura nenhuma**. 24 execuções, ~11 h, ~US$ 175. Documento completo em
`experiments/CONTROLE.md`.

| braço | relógio | US$ | ganho |
|---|---|---|---|
| sessão única morta aos 106 s | 106 s | 0,53 | 4,55× |
| sessão única, parada natural | 527 s | 2,62 | 4,32× |
| **AVO completo, 3 passos** | **2 439 s** | **11,44** | **4,92×** |
| sessão única retomada até o orçamento | 2 219 s | 17,92 | 5,20× |

> **Ressalva que muda a leitura:** por causa da falha 8, o braço `greedy` rodou
> **cego** — nunca conseguiu executar o avaliador. A comparação medida é "o AVO
> contra um agente que não pode medir", não "contra o mesmo modelo com o mesmo
> `f`". Detalhes em `experiments/CONTROLE.md`, no topo.

**Nenhuma comparação é distinguível** — todos os p ajustados por Holm deram
1,000. A mais limpa (`+10%` de desbalanço de relógio) mede −0,277× com IC95
[−0,983, +0,363].

O `full` fez três coisas que o `greedy` não fez, e nenhuma delas é média:
**ninguém desistiu** (7 de 7 sementes alteraram código; no `greedy` uma em quatro
terminou com o arquivo intacto, 6 avaliações e **0 edições**); ele **espalha
menos** (desvio 0,26–0,39 contra 0,38–1,89, hipótese exploratória e sem poder
para testá-la); e o `greedy` **não gasta o orçamento que recebe** — mandado usar
2 471 s, para aos 731.

Mas a conclusão que importa é sobre o alvo, não sobre a arquitetura: **este alvo
não testa o AVO.** E ela sobrevive à falha 8 — na verdade fica mais forte, porque
foi um agente **cego** que capturou 68% do ganho disponível. Um alvo cuja KB
entrega a resposta sem precisar medir não discrimina arquitetura nenhuma.

Foi daí que saiu a falha 7 e a sonda que a pega por US$ 0,50. Dos seis alvos, só
o `sql_agg` sobrevive a ela — e é nele que a próxima ablação tem chance de medir
alguma coisa, agora com os agentes enxergando.

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
