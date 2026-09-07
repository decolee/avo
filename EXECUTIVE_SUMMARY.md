# AVO Data Lab — o que este repositório estabeleceu

Reprodução aberta da arquitetura AVO (arXiv:2603.24517) aplicada a engenharia de
dados: um coding agent como operador de variação numa busca evolutiva, com um
avaliador objetivo como árbitro.

**Estado em 2026-09-07.** US$ 1.222 em compute de agente, 51 runs de experimento,
389 commits. Este arquivo é o ponto de entrada; cada afirmação aponta para o
relatório que a sustenta.

---

## 1. O achado sólido: o loop funciona

| experimento | n | melhoria sobre o seed |
|---|---|---|
| `sql_workload` (ablação 3) | 20 | **7,38×** |
| `sql_agg` (Fase 2A) | 11 | **4,95×** |
| `sql_agg` (ablação 1) | 20 | **5,06×** |

51 runs, 160 passos no maior deles, **nenhum run abaixo de 4,22×**. O gate de
correção segurou: nenhum candidato aceito foi depois encontrado trapaceando, e a
bateria anti-trapaça (`REWARD_HACKING.md`, `tests/test_anticheat.py`) cobre
memoização, cache em disco e detecção de dataset.

Um agente com um `f` objetivo, um incumbente e um gate melhora artefatos de
engenharia de dados em 4–7× de forma repetível. É o resultado que viaja.

## 2. O que NÃO foi demonstrado: que a arquitetura importa

Três execuções pagas, todas nulas:

| fase | contraste | efeito | distinguível? | relatório |
|---|---|---|---|---|
| ablação 1 | componentes (`sql_agg`) | −3,5% a −4,5% | não | `ABLATION.md` |
| 2A | `full` × `greedy` (`sql_agg`, n=11) | +4,9% | não (p Holm 0,103) | `FASE2_SQL_AGG.md` |
| 3 | componentes (`sql_workload`, n=5) | −5,5% a +5,7% | não (p Holm 1,000) | `ABLACAO_RESULTADO.md` |

Na ablação 1 os braços **mutilados pontuaram acima** do completo.

**"Não distinguível" não é "não existe".** A resolução da bancada é ~5,5%;
andaime que valha menos que isso é invisível aqui. Separar o `no_supervisor` do
ruído exigiria n≈41 por braço — US$ 1.889 e ~119 h por par.

E **não há poder barato**: com os dados na mão, duas formas de baixar a variância
foram testadas e falharam. Parear por índice de semente (r médio **+0,14**; piora
39% num braço) e fixar o denominador (piora em 3 de 4 — a razão com denominador
próprio já cancela deriva de máquina). A variância é estocasticidade do agente, e
comprá-la é linear no n.

## 3. O eixo que a bancada nunca variou

**Os 51 runs rodaram um único modelo**, `claude-opus-5`. O que variou foi sempre
o andaime. Nenhum experimento daqui diz nada sobre capacidade de modelo — e,
portanto, nada sobre trajetória rumo a sistemas mais gerais.

Há um limite mais fundo, declarado no próprio `CLAUDE.md`: o método só fecha onde
existe `f` objetivo. **Esta bancada exclui por desenho a classe de problema em
que a pergunta sobre generalidade é interessante.** O que ela mede bem é
competência estreita e verificável.

O eixo foi aberto em 2026-09-07 (`runner.py --modelo`) e pré-registrado em
`FASE_MODELO.md`, com critério de parada declarado: se o piloto disser n>20, o
experimento **não roda** e fica registrado que o eixo do modelo também está
abaixo da resolução desta bancada.

## 4. O produto reutilizável: o método

Os nulos não viajam. Isto viaja:

- **`docs/TARGET_DESIGN.md`** — nove propriedades de um alvo válido, cada uma
  nascida de um alvo perdido por não tê-la. A §3g (como construir um alvo que uma
  sessão só não esgota) e o requisito de headroom graduado são as mais fáceis de
  errar.
- **`targets/sql_workload/`** — o primeiro alvo construído de trás para frente a
  partir da §3g. Nove artefatos, headroom medido de 6,77× em 8 movimentos, e a
  propriedade que o justifica: **o mesmo `setup.sql` vale 1,14× aplicado às
  consultas do seed e 2,10× aplicado às reescritas.** Movimentos que se destravam.
- **`docs/ABLATION_PROTOCOL.md`** + os pré-registros — o desenho declarado antes
  do dado, com os desvios nomeados.
- **`experiments/DEFEITOS.md`** — o registro de defeitos de instrumento. Um erro
  na bancada faz o experimento medir outra coisa que não a que diz medir; achar
  um vale mais que um resultado.

## 5. A disciplina, e o teste de fogo dela

Três decisões desta rodada foram tomadas contra o próprio interesse:

1. **O ADENDO do pré-registro** foi escrito com 12 dos 20 runs prontos e nenhuma
   estatística rodada — custou-me a exclusão de duas sementes do braço de
   referência, e foi registrado antes de eu saber que não mudaria nada (não mudou).
2. **O detector de cegueira não foi consertado durante o experimento**, embora eu
   já tivesse a evidência do conserto. Alterar um instrumento logo depois de ele
   reprovar runs do próprio braço de referência é o movimento que a disciplina
   existe para impedir, mesmo estando certo. Foi consertado depois, com a
   verificação explícita de que a conclusão publicada não mudava.
3. **A hipótese "o `full` é mais consistente"** (cv 4,4% contra 6,9/12,0/15,9%)
   foi testada por permutação antes de virar frase — p entre 0,38 e 0,60,
   **não se sustenta**. Está registrada como testada e descartada.

## 6. Onde entrar

| quero... | leia |
|---|---|
| o resultado do último experimento | `experiments/ABLACAO_RESULTADO.md` |
| construir um alvo | `docs/TARGET_DESIGN.md`, depois `targets/sql_workload/` |
| entender o que é da NVIDIA e o que é desta reprodução | `docs/AVO_REPLICATION_REPORT.md` |
| saber o que já quebrou | `experiments/DEFEITOS.md` |
| rodar a próxima fase | `experiments/FASE_MODELO.md` |
| operar a bancada | `docs/RUNBOOK.md`, `CLAUDE.md` |

## 7. A recomendação de quem fecha

**Não comprar mais ablação de componentes.** Três experimentos, US$ 883 nos
principais, placar zero, e a matemática diz que a resposta custa mais que vale.

**A Fase 2B (`full` × `greedy` com compute equiparado) é menos interessante do que
parece.** As duas medidas que existem discordam por 6× (+4,9% com n=11 contra
+32% com n=1 no `full`), e a maior tem o n menor.

**O eixo do modelo é a pergunta aberta**, e agora é executável. O piloto decide se
ela é pagável, e o critério de parada está declarado antes do dado.
