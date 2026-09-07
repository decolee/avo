# Ablação de componentes no `sql_workload` — resultado

20 runs, 160 passos, US$ 475,36, 29 h de relógio. Executado contra o pré-registro
em `experiments/ABLACAO_SQL_WORKLOAD.md`, que não foi editado depois do primeiro
run — a única correção está no `ADENDO 2026-09-06`, escrito com 12 dos 20 runs
prontos e antes de qualquer estatística.

## O resultado, em uma frase

**Remover a KB, a memória entre passos ou o supervisor não produziu diferença
distinguível do ruído.** Os quatro braços chegam a 7,0×–7,8× de melhoria sobre o
seed, e o efeito mínimo detectável com n=5 nesta bancada é 0,41× — maior que dois
dos três contrastes observados.

## Primário, como pré-registrado

Métrica: `primary_final / primary_seed`. Bootstrap de 10.000 reamostragens para o
intervalo, permutação para o p, Holm-Bonferroni sobre as três comparações.

| braço | n | média | mediana | Δ vs `full` | IC 95% | p Holm | rejeita? |
|---|---|---|---|---|---|---|---|
| `full` | 5 | **7,396** | 7,369 | — | — | — | — |
| `no_kb` | 5 | 7,285 | 7,267 | −0,111 | [−0,575, +0,367] | 1,000 | não |
| `no_memory` | 5 | 7,829 | 7,275 | +0,433 | [−0,362, +1,579] | 1,000 | não |
| `no_supervisor` | 5 | 6,999 | 7,047 | −0,396 | [−1,161, +0,243] | 1,000 | não |

Os três intervalos cruzam o zero com folga. **Efeito mínimo detectável: 0,410.**

Valores por semente:

| braço | s0 | s1 | s2 | s3 | s4 | dp | cv |
|---|---|---|---|---|---|---|---|
| `full` | 7,899 | 7,369 | 7,479 | 7,189 | 7,042 | 0,328 | 4,4% |
| `no_kb` | 7,320 | 8,023 | 7,217 | 6,597 | 7,267 | 0,506 | 6,9% |
| `no_memory` | 7,105 | **10,009** | 7,275 | 7,687 | 7,070 | 1,243 | 15,9% |
| `no_supervisor` | **5,643** | 7,564 | 7,800 | 6,943 | 7,047 | 0,838 | 12,0% |

As duas diferenças de média que existem vêm cada uma de **um run**: o 10,009 do
`no_memory` s1 e o 5,643 do `no_supervisor` s0. Tire os dois e as quatro médias
caem dentro de 0,3× umas das outras. A mediana já mostra isso sem tirar nada: a do
`no_memory` é 7,275 contra 7,369 do `full` — a média dele é maior, a mediana é
menor.

## Sensibilidade: o portão estrito

O `destilar_logs.py` reprovou **7 de 160 sessões-passo**, atingindo 6 sementes. O
`ADENDO` explica por que elas ficam no primário. Aplicando o portão ao pé da
letra assim mesmo, restam 14 sementes:

| braço | n | média | Δ vs `full` | IC 95% | p Holm |
|---|---|---|---|---|---|
| `full` | 3 | 7,377 | — | — | — |
| `no_kb` | 4 | 7,290 | −0,087 | [−0,730, +0,532] | 1,000 |
| `no_memory` | 5 | 7,829 | +0,452 | [−0,462, +1,692] | 1,000 |
| `no_supervisor` | 2 | 6,603 | −0,774 | [−2,020, +0,473] | 1,000 |

**As duas análises concordam: nulo.** A divergência que o ADENDO se comprometeu a
reportar não existe — a decisão sobre o portão não mudou a conclusão.

### A auditoria das 7 sessões

| sessão | tentou medir | detectado | aceito | Δ primary |
|---|---|---|---|---|
| `full-s1/step8` | 7 | 0 | não | 0 |
| `full-s2/step8` | 10 | 0 | não | 0 |
| `no_kb-s4/step3` | 4 | 0 | **sim** | +0,624 |
| `no_kb-s4/step8` | **0** | 0 | não | 0 |
| `no_supervisor-s2/step7` | 3 | 0 | não | 0 |
| `no_supervisor-s3/step8` | 2 | 0 | **sim** | +0,031 |
| `no_supervisor-s4/step6` | 14 | 0 | não | 0 |

Seis das sete mediram; o detector é que não reconhece a forma. As duas **aceitas**
— as únicas em que o argumento "passo rejeitado, não contamina" não bastaria —
foram lidas uma a uma: `no_kb-s4/step3` rodou `./avo-eval` quatro vezes em laço
mais uma comparação pareada contra `git show v2:`; `no_supervisor-s3/step8` rodou
quatro vezes. As duas canalizaram o stdout para `python3 -c "import json..."`, que
é exatamente o falso negativo do ADENDO.

A sétima, `no_kb-s4/step8`, **não tentou medir nenhuma vez** — cega de verdade.
Teve o passo rejeitado e Δ primary zero, então não entra no número de jeito nenhum.

## Secundárias

| braço | aceitos/40 | passos até 1º platô | US$/run | turnos/passo | US$ por 1× |
|---|---|---|---|---|---|
| `full` | 31 | 4,8 | 25,18 | 35,6 | 3,40 |
| `no_kb` | 34 | 4,0 | 19,97 | 29,3 | 2,74 |
| `no_memory` | 27 | 6,0 | 29,02 | 39,3 | 3,71 |
| `no_supervisor` | 30 | 6,2 | 20,90 | 30,0 | 2,99 |

O padrão mais legível está no `no_memory`: **mais caro (US$ 29,02/run) e com menos
commits aceitos (27/40) que qualquer outro braço**, com mais turnos por passo. Sem
`NOTES.md`, o agente re-explora — é o que a regra do laboratório sobre becos sem
saída prevê. Mas isso é leitura de tabela descritiva com n=5, não resultado
testado, e nenhuma dessas colunas foi pré-registrada com teste.

### Uma hipótese post-hoc que NÃO se sustentou

O `full` tem o menor cv (4,4% contra 6,9%, 12,0% e 15,9%), o que sugeriria
"a arquitetura completa não ganha mais, ganha mais consistentemente". Testei por
permutação sobre o desvio-padrão, 10.000 reamostragens:

```
no_kb          dp=0.506 vs full=0.328   p=0.4130
no_memory      dp=1.243 vs full=0.328   p=0.6027
no_supervisor  dp=0.838 vs full=0.328   p=0.3778
```

**Não se distingue.** Fica registrado como testado e não sustentado, não como
achado. Com n=5 a dispersão é ainda menos estimável que a média.

## O que este experimento não pode dizer

1. **Que os componentes não fazem diferença.** O pré-registro já dizia, no desvio
   5, que n=5 detecta com confiança apenas efeitos da ordem de 30%, e que os
   contrastes de remover **um** componente deveriam ser menores que o `full` ×
   `greedy` de 20–32% do piloto. Foi exatamente o que aconteceu. **"Não
   distinguível" não é "não existe"** — para o `no_supervisor`, cujo Δ observado é
   −0,396 e o desvio combinado 0,636, separá-lo do ruído a 5% exigiria
   n ≈ 41 por braço (`n ≈ 2·(2,8·s/Δ)²` = 40,3) — US$ 1.889 e ~119 h só para o par
   `full` × `no_supervisor`.
2. **Nada sobre o supervisor com orçamento justo.** O desvio 4 do pré-registro
   declara que o orçamento é igualado por **passos**, não por tokens, e que isso
   favorece o `full`. A tabela confirma o mecanismo: `full` gastou US$ 25,18/run
   contra US$ 20,90 do `no_supervisor`, 20% a mais pelos mesmos 8 passos. O
   `no_supervisor` ficou 0,396 **abaixo** mesmo com o desenho inclinado a favor do
   `full` — o que só torna a leitura mais conservadora, não mais forte.
3. **Nada sobre `no_lineage`.** Declarado ausente no desvio 2, e continua ausente.
4. **Nada sobre `full` × `greedy`.** Desvio 3: fica para uma fase própria. O
   contraste do piloto (7,42× × 5,620×) **não entra aqui** — é dado de piloto.

## O que fica para o repositório

**Recomendação 1 — consertar o detector de sessão cega. FEITA (2026-09-07),
depois de este relatório ser publicado.** O detector errava nos dois sentidos: ler
o fonte do avaliador contava como tentativa de medir (254 `cat`, 227 `sed`, 126
`grep` em 300 transcrições), e saída parseada não contava como medição. O conserto
separa "executa ou só lê?" de "o que voltou tem forma de medição?" e exige as
duas — a forma do resultado sozinha dá 16,9% de falso positivo, porque
`cat NOTES.md` devolve `primary = 1.16` em prosa. Registro completo e validação
em `DEFEITOS.md` §17.

**O conserto não muda nada aqui.** Com o portão corrigido a sensibilidade mantém
**19 das 20 sementes** (só a `no_kb-s4` sai, a única com uma sessão de 0
tentativas), e os três contrastes seguem nulos:

| braço | n | Δ vs `full` | IC 95% | p Holm |
|---|---|---|---|---|
| `no_kb` | 4 | −0,106 | [−0,660, +0,458] | 1,000 |
| `no_memory` | 5 | +0,433 | [−0,362, +1,579] | 1,000 |
| `no_supervisor` | 5 | −0,396 | [−1,161, +0,243] | 1,000 |

O detector corrigido também **não absolve** a Fase 2A: lá ele ainda marca 13 de
100 sessões como genuinamente cegas (antes 19), todas do braço `full` — o defeito
de permissão era real.

**Recomendação 2 — a próxima fase é `full` × `greedy`, não mais componentes.**
Este experimento gastou US$ 475 para medir contrastes que o próprio pré-registro
previa serem menores que a resolução da bancada. O contraste que o piloto mostrou
ser pagável é o de arquitetura contra modelo. Repetir a ablação de componentes com
n=41 custaria US$ 1.889 e ~119 h para **um** par de braços, respondendo uma
pergunta mais fina que a que ainda não foi respondida.

**Recomendação 3 — `check_poder` com 5% cravado. FEITA (2026-09-07).** O
comentário do próprio check dizia *"não há barra universal: o que decide é o custo
por semente, que é do experimento e não do alvo"*, e o código logo abaixo cravava
uma barra universal de 5%. O `sql_workload` levava aviso por precisar de n=45 para
5% — uma precisão que nenhum experimento daqui pediu nem pagou. Agora o alvo pode
declarar `lab.piloto_efeito_alvo`, e o n sai do mesmo piloto por
`n(d) = n(5%)·(0,05/d)²`. Sem a declaração o comportamento é o de antes, para não
mudar o veredito de alvo nenhum em silêncio. O `sql_workload` declara 30% — a
ordem do contraste que esta bancada persegue — e passa com n=2.

## Reprodução

```
python3 experiments/ablacao/runner.py --alvo sql_workload --passos 8 \
    --rodadas 5 --timeout-agente 20m --effort medium \
    --saida experiments/ablacao/resultados/ablacao_sql_workload

python3 experiments/ablacao/analise.py \
    --resultados experiments/ablacao/resultados/ablacao_sql_workload/results.jsonl
```

Dados brutos: `experiments/ablacao/resultados/ablacao_sql_workload/results.jsonl`
(20 linhas, uma por run, com os 8 passos de cada). Transcrições em
`runs/<braço>-s<n>/*/logs/step-*.log`, fora do git.

## Números do experimento

| | |
|---|---|
| runs | 20 (4 braços × 5 sementes, intercalados por rodada) |
| passos | 160 |
| aceitos | 122 (76%) |
| falhas de agente | 8 (5%), das quais 6 por estouro de relógio |
| custo | US$ 475,36 (estimado no pré-registro: US$ 465) |
| relógio | 29,0 h |
| `primary` do seed | 1,166 ± 0,160 |
| `primary` final médio | 8,568 |
| melhor run | `no_memory` s1, 10,009× |
