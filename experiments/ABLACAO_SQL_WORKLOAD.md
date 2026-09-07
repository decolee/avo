# Ablação de componentes no `sql_workload` — pré-registro dos desvios

**Escrito ANTES de rodar.** O desenho é o de `docs/ABLATION_PROTOCOL.md`; este
arquivo declara só onde esta execução se afasta dele, e por quê. Nada abaixo
pode ser editado depois de o primeiro run começar — correções vão para uma seção
`ADENDO` datada, no fim.

## O que roda

```
python3 experiments/ablacao/runner.py --alvo sql_workload --passos 8 \
    --rodadas 5 --timeout-agente 20m --effort medium \
    --saida experiments/ablacao/resultados/ablacao_sql_workload
```

Quatro braços × 5 sementes = 20 runs de 8 passos. Ordem **intercalada e
embaralhada por rodada** (`random.Random(1000 + rodada)`), como o protocolo exige.

| braço | o que muda |
|---|---|
| `full` | nada — AVO completo |
| `no_supervisor` | sem detecção de estagnação nem redirecionamento |
| `no_kb` | knowledge base vazia |
| `no_memory` | `NOTES.md` zerado entre passos |

Custo estimado: **~US$ 465**, ~25 h de relógio. Base: o piloto mediu US$ 22,61 e
76 min por run de 8 passos neste alvo.

## Métrica primária, fixada aqui

`primary_final / primary_seed`, a mesma de §5 do protocolo. Secundárias: commits
aceitos, passos até o primeiro platô, score por regime.

## Desvios declarados

**1. O alvo é o `sql_workload`, não `etl_agg` nem `sql_agg`.**
O protocolo §6 pede "`etl_agg` e `sql_agg` no mínimo". O `etl_agg` reprova em §3
(1,61× em 2 movimentos) e o `sql_agg` foi usado na Fase 2A, cujo resultado foi
nulo com n=11. O `sql_workload` é o único alvo do repositório que passa em §3f
com efeito pagável (`experiments/RELATORIO_SQL_WORKLOAD.md`). Rodar de novo num
alvo que já não distinguiu nada seria gastar para repetir um resultado conhecido.

**2. Quatro braços dos cinco. Falta `no_lineage`.**
Ele exige um invólucro que reescreve o prompt de variação para esconder o
histórico de versões, e esse invólucro não existe no `runner.py`. Escrevê-lo
agora significaria estrear código não testado dentro de um experimento de US$ 465.
Fica declarado como ausente, não como feito.

**3. O controle `greedy` NÃO entra nesta fase.**
O protocolo §3 o define como o braço que responde "quanto vem do modelo". O
piloto já o mediu neste alvo (5,620× ± 0,478 contra 7,42× do `full`), mas **dado
de piloto não entra em análise** — é a regra do próprio piloto. Incluí-lo aqui
exigiria equipará-lo por orçamento ao `full` (76 min por sessão, não os 900 s do
piloto), o que somaria ~6 h e o tornaria um experimento diferente do que os
outros quatro braços formam entre si. **Esta fase é uma ablação de componentes,
internamente completa: os quatro braços são comparáveis entre si e intercalados
entre si.** O contraste `full` × `greedy` fica para uma fase própria.

**4. O orçamento é igualado por PASSOS (8), não por tokens.**
O protocolo §4 diz explicitamente que igualar por passos **não basta**, porque um
passo com supervisor custa mais. O `runner.py` iguala por passos. Isso favorece
sistematicamente o `full` e o `no_kb` contra o `no_supervisor` — na direção de
inflar o efeito do supervisor. **É a limitação mais séria desta execução** e
qualquer diferença a favor do `full` sobre o `no_supervisor` tem que ser lida com
ela em mente. O custo por braço é registrado em `results.jsonl` e será reportado.

**5. n=5, e o que n=5 não faz.**
Repetido aqui porque o protocolo manda repetir:

> Com n=5 e o ruído desta bancada, o experimento detecta com confiança apenas
> efeitos **da ordem de 30% ou mais**. O piloto mediu o contraste `full` ×
> `greedy` em 20–32%; os contrastes entre `full` e a remoção de UM componente
> devem ser **menores que isso**. É provável que este experimento não os
> distinga do ruído, e **"não distinguível" não é "não existe"**.

Declarar isso antes é o ponto.

## Análise, fixada aqui

- Bootstrap, 10.000 reamostragens, intervalo da diferença de cada braço contra `full`.
- Holm-Bonferroni sobre as três comparações contra `full`.
- `destilar_logs.py` rodado **antes** da análise; qualquer sessão cega invalida a
  semente, não vira ruído na amostra.
- Efeito e intervalo sempre reportados; p-valor sozinho com n=5 não informa nada.

---

## ADENDO 2026-09-06 — o detector de sessão cega tem falso negativo

**Escrito com 12 dos 20 runs prontos, antes de qualquer estatística.** Registrado
aqui, e não no relatório, porque muda como a regra pré-registrada se aplica — e
uma mudança dessas escrita depois de ver o resultado final não valeria nada.

A análise pré-registrada manda rodar `destilar_logs.py` antes de tudo: *"qualquer
sessão cega invalida a semente, não vira ruído na amostra."* Rodado sobre os 12
runs, o portão reprova **3 de 104 sessões-passo**:

```
3 de 104 sessoes terminaram sem medir NADA:
full-s1/step-0008, full-s2/step-0008, no_supervisor-s2/step-0007
```

Fui ler as três transcrições. **As três mediram** — muito. O que elas não fizeram
foi medir do jeito que o detector sabe reconhecer.

`destilar_logs._SAIDA_DO_AVALIADOR` reconhece uma medição bem-sucedida por duas
strings no resultado da ferramenta: `avo_result` e `medianas:`. São as do stdout
**padrão** do avaliador. Um agente que canaliza esse stdout para um parser, ou que
importa `medir()` do `eval.py` direto para montar comparação pareada, produz um
resultado que não contém nenhuma das duas. Foi o que as três fizeram:

- `full-s2/step-0008` — 10 chamadas ao avaliador, 0 recusas de permissão. A
  última: `./avo-eval | python3 -c "import json,sys;d=json.load(...)"`, devolvendo
  `correct= True primary= 10.0007 {'estreito': 40.166, 'frio': 2.543, 'quente': 9.791}`.
  Antes dela, seis medições pareadas alternando candidatos (`v6`/`q8a`/`q8b`/`ord`).
- `full-s1/step-0008` — 7 chamadas. Harness pareado próprio:
  `base 9.8685 True {...} / novo 10.0411 True {...} / base 9.2744 ... / novo 9.8531 ...`
- `no_supervisor-s2/step-0007` — 3 chamadas, incluindo `EXPLAIN QUERY PLAN` das 8
  consultas e uma decomposição de custo por estágio da q1 nos três regimes.

Ou seja: o detector marca como cega exatamente a sessão que mede **melhor** que o
esperado — a que desconfia do ruído e faz medição pareada, que é o que
`kb/20-medicao.md` do alvo manda fazer. É defeito de instrumento nº 17
(o 14 já era o container recuperado por ociosidade; ver `DEFEITOS.md`).

Há ainda um segundo motivo, independente, pelo qual essas três não podem
contaminar a média: **as três tiveram o passo rejeitado.** `codigo_mudou: false`,
`aceito: false`, `primary_depois == primary_antes` nas três. O número delas não
entra em `melhoria_relativa` de jeito nenhum — o mecanismo de contaminação que a
regra existe para bloquear (uma sessão que escreveu no escuro e teve o score
contado) não tem por onde agir aqui.

**O que decidi, e o que não decidi.**

A regra pré-registrada continua valendo como escrita: uma sessão que não mediu
invalida a semente. O que mudou é o fato, não a regra — a premissa "não mediu" é
falsa nas três, e está demonstrada acima com a saída das próprias chamadas.
Então:

- O primário sai **sem excluir essas sementes**.
- O relatório traz **também** a análise com o portão estrito aplicado ao pé da
  letra, como sensibilidade. Se as duas divergirem, as duas ficam no relatório e
  a divergência é o resultado.
- **Não vou consertar `destilar_logs.py` no meio do experimento.** Alargar o
  padrão de um detector logo depois de ele reprovar dois runs do meu próprio
  braço de referência é o movimento que a disciplina deste laboratório existe
  para impedir, mesmo quando o conserto está certo. Fica como recomendação, com
  a evidência acima anexada.

O custo de não decidir isto agora seria decidir depois de saber quanto vale — e
aí não haveria como distinguir uma correção de uma conveniência.
