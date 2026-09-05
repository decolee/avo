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
