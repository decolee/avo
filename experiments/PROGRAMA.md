# O programa — estado, preços e como retomar

Documento vivo. Ele existe porque o programa leva ~98 h de relógio e não cabe
numa sessão: se esta for interrompida, o que está aqui basta para retomar.

**Comando único, retomável, seguro de rodar de novo a qualquer momento:**

```bash
python3 experiments/ablacao/programa.py            # roda o que falta
python3 experiments/ablacao/programa.py --plano    # só mostra o estado
```

Ele pula o que já está no disco, relança a fase que morrer, e nunca roda duas
coisas ao mesmo tempo — o `f` deste laboratório é vazão em wall-clock, e dois
agentes juntos contaminam exatamente o número que o experimento compara.

## Quando o container reiniciar

Aconteceu uma vez às 20h24 do dia 2, com o `full` s1 no quarto de oito passos.
O que fazer é uma linha:

```bash
setsid nohup python3 experiments/ablacao/programa.py >> <log> 2>&1 < /dev/null &
```

Ele pula fase completa, pula semente completa, e **retoma semente pela metade**
do passo em que parou — `_reaproveita_run` acha o run dir com passos feitos e
`avo run --resume` continua dali. Sem isso um reinício custava a semente inteira,
1,3 h de agente. Com isso custa o passo que estava em voo.

Três coisas que valem conferir depois de retomar, nesta ordem:

```bash
python3 experiments/ablacao/programa.py --plano     # o que falta
git log --oneline -5                                 # o que sobreviveu
ps -eo args | grep -c "[p]rograma.py"                # 1 = rodando
```

O que **não** sobrevive: o processo, e nada mais. Cada semente é commitada assim
que fecha, então o pior caso é perder o passo em voo.

## As fases

| # | o que responde | n | relógio | US$ |
|---|---|---|---|---|
| sondas | as frações de §3e medidas com o agente **enxergando** | 5 alvos | 0,3 h | ~3 |
| **2A** | a estrutura do AVO bate o modelo sozinho? | 11 | 28 h | ~250 |
| **2B** | ou o `full` só ganhou por ter mais compute? | 11 | 26 h | ~760 |
| **3** | qual componente contribui (KB, memória, supervisor) | 6 | 43 h | ~380 |

Total previsto: **~98 h e ~US$ 1.400**, dentro do teto autorizado de US$ 10 mil.
O recurso escasso aqui é relógio, não dinheiro — é por isso que a Fase 3 roda com
n=6 (detecta ~7%) em vez de 11 (detecta 5%), e por isso ela **reusa as sementes
do `full` de 2A** como braço de referência, economizando 26 h.

## Estado em 2026-09-07: a Fase 3 rodou, e o que ela decide

A Fase 3 foi executada no `sql_workload` (não no `sql_agg`), com 4 braços × n=5,
US$ 475 e 29 h — `ABLACAO_RESULTADO.md`. **Resultado nulo nos três contrastes**,
com efeito mínimo detectável de 0,41× sobre uma base de 7,4× (5,5%).

Somando as três execuções pagas, o placar da arquitetura é:

| fase | contraste | efeito | distinguível? |
|---|---|---|---|
| ablação 1 | componentes (`sql_agg`) | −3,5% a −4,5% | não |
| 2A | `full` × `greedy` (`sql_agg`, n=11) | +4,9% | não |
| 3 | componentes (`sql_workload`, n=5) | −5,5% a +5,7% | não |

**A recomendação que fecha esta fase: não comprar mais ablação de componentes.**
Separar o `no_supervisor` do ruído exigiria n≈41 por braço — US$ 1.889 e ~119 h
para **um** par. E não há poder barato disponível: com os dados da Fase 3 na mão,
duas formas de baixar a variância foram testadas e as duas falharam.

- **Parear por índice de semente:** r médio **+0,14** entre braços. O índice não
  carrega sinal comum; parear chega a piorar a variância da diferença em 39% no
  `no_supervisor`.
- **Fixar o denominador** (a `primary_seed` varia cv 13,8%, max/min 1,44×): piora
  em 3 dos 4 braços. A razão com denominador próprio já cancela a deriva de
  máquina — o desenho atual estava certo.

A variância é estocasticidade do agente, e comprá-la é linear no n.

A Fase 2B (`full` × `greedy` com compute equiparado) continua sendo o único
contraste com sinal — mas o piloto do `sql_workload` mediu +32% e a Fase 2A mediu
+4,9% no mesmo contraste. **Os dois discordam por 6×**, e o piloto tinha n=1 no
`full`. Entrar nela sabendo que pode ser mais um nulo.

## Por que esta é a terceira tentativa

As duas anteriores produziram intervalos que continham zero, por três causas
distintas. Todas consertadas, todas verificadas, todas com uma checagem que
impede a repetição:

| causa | conserto | verificação |
|---|---|---|
| alvo saturado — 100 s pegavam 68% do headroom | `sql_agg`, único a passar em §3e | `sonda.py`, cobrado pelo `avo-lab verify` |
| supervisor nunca disparava (36 passos, 0 disparos) | `--stagnation-window 2`, 8 passos | disparou 2× no piloto |
| **agentes não conseguiam medir** | `--allowed-tools` | `destilar_logs.py` sai 1 se alguma sessão for cega |
| n escolhido pelo orçamento | piloto de potência primeiro | CV 4,2% → n=11 detecta 5% |

A terceira é a mais séria e está no README como falha 8: em dois experimentos e
US$ 343, **nenhum agente conseguiu executar o avaliador**. O modo `acceptEdits`
libera edição de arquivo e exige aprovação para Bash, que nunca vem num run não
supervisionado. Os agentes escreveram código no escuro e os experimentos
reportaram números como se eles tivessem medido.

## O que o piloto já diz (n=1 e n=5, não é o experimento)

`full` 8 passos: **4,78×**, US$ 21,18, 2,4 h — com platô no passo 4 e o
supervisor disparando nos passos 7 e 8 sem resgatar nada.
`greedy` uma sessão: **4,55×**, US$ 1,57, 6 min.

Se isso se sustentar em 11 sementes: **a estrutura compra ~5%, por 13× mais
dinheiro e 25× mais relógio.** Um número pequeno, e com a forma certa — a NVIDIA
obteve 3,5% sobre o cuDNN em sete dias de B200. Ganho de arquitetura de busca,
quando o incumbente já é bom, mora nessa ordem de grandeza.

## Antes de analisar qualquer fase

```bash
python3 experiments/ablacao/destilar_logs.py --logs <dir>/logs   # precisa sair 0
python3 experiments/ablacao/analise_controle.py --resultados <dir>/results.jsonl --greedy <dir>/greedy.jsonl
```

A primeira linha não é opcional. Uma sessão cega não é ruído a mais na amostra: é
uma sessão que não testa o que o desenho diz testar.

## Onde ficam as coisas

```
experiments/ablacao/resultados/fase2_sql_agg/
  results.jsonl     full, no_supervisor, no_kb, no_memory  (um objeto por semente)
  greedy.jsonl      greedy_nat, greedy_cont
  parcial.jsonl     um objeto por PASSO dos braços do harness
  logs/             transcrições stream-json (fora do git, grandes)
  runs/             árvores de trabalho de cada run

experiments/ablacao/resultados/piloto_sql_agg/        piloto válido (agente vendo)
experiments/ablacao/resultados/piloto_sql_agg_CEGO/   piloto inválido, com LEIA.md
```

## Pré-registros

- `experiments/FASE2_SQL_AGG.md` — 2A, com o poder calculado antes do primeiro dado
- `docs/ABLATION_PROTOCOL.md` — o protocolo geral e os controles não negociáveis
- `experiments/CONTROLE.md` — o experimento anterior, com a correção no topo
