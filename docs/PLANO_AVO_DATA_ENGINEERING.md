# PLANO AVO PARA ENGENHARIA DE DADOS — validado empiricamente

**Não é proposta. É relatório de execução.** Construí um target do seu domínio, rodei o harness real e registro abaixo o que funcionou, o que quebrou e o que isso implica.

> **Nota de estado (v2).** Este documento é o registro histórico do primeiro
> ciclo e continua valendo como tal — as falhas descritas na §3 aconteceram de
> verdade e são o motivo de o laboratório ter a forma que tem. O que mudou desde
> então:
>
> - As três falhas viraram **verificação automática**: mutantes obrigatórios
>   (`--selftest`), dimensionamento verificado (`--budget`), e testes que
>   recusam um alvo sem gate. Ver `docs/TARGET_DESIGN.md`.
> - Uma **quarta falha** apareceu ao corrigir a segunda, e é a mais séria das
>   quatro para o propósito científico da bancada: veja a §3.4 abaixo.
> - O `etl_agg` foi reconstruído; os números da §2 são do alvo antigo e estão
>   mantidos como registro do que foi medido na época, não como estado atual.
> - Os tiers ganharam um degrau intermediário: **SQLite** antes de Postgres,
>   porque roda no CI sem servidor e o que se aprende transfere.

---

## 1. O que foi construído e executado

**Target `etl_agg`** — análogo Tier 0 do experimento de kernel: agregação de transações financeiras (JSONL → dict por `account|ccy`), com `n`, `gross`, `net` (só `settled`) e `last_ts`.

- Dataset congelado determinístico: 180.000 registros, 1.500 contas, 3 moedas, 19,6 MB, seed fixo.
- Gate de correção: **SHA256 sobre itens ordenados** — insensível à ordem de inserção, sensível a valores.
- Score: geomean de throughput em três regimes (`cold`, `best`, `median`) sobre 5 execuções.
- KB com contrato + notas de performance.

## 2. Resultados medidos

| Versão | primary | cold | best | median | Aceita? | Motivo do framework |
|---|---|---|---|---|---|---|
| v0 (seed) | 0,03657 | 0,0365 | 0,0367 | 0,0365 | — | seed x₀ |
| v1 (passe único) | **2,1131** | 2,0375 | 2,1677 | 2,1363 | ✅ | melhora sobre v0 |
| v2 (arredondamento incremental) | 1,7152 | — | — | — | ❌ | `regression against v1: 1.7152 vs 2.1131 (-0.397899)` |

**Ganho v0→v1: 57,8×** (27,4s → 0,47s por execução). Um único passe com acumulação em dict, substituindo o reagrupamento O(n×grupos) do seed.

**Persistência verificada:** tags git `v0` e `v1` no `work/`, `.avo/scores.jsonl` com vetor de score completo por versão, e `rejected/step-0002.patch` arquivando o diff descartado. O `steps_since_best` foi para 1 após a rejeição — é o contador que alimenta o supervisor.

## 3. As três falhas encontradas (o valor real deste exercício)

### Falha 1 — Meu gate de correção era fraco, e isso passou despercebido

Submeti deliberadamente uma versão que arredonda `gross`/`net` **a cada acumulação** em vez de no final — uma violação do contrato declarado na KB. **O gate aceitou como correta.** Só foi rejeitada porque ficou mais lenta.

Por que passou: os `amount` já têm 2 casas decimais, e o erro de ponto flutuante acumulado ficou abaixo do limiar de `round(x, 2)`. O hash não divergiu.

Isso é exatamente o teto de verificadores imperfeitos de *Inference Scaling fLaws* (arXiv:2411.17501): com falsos negativos no verificador, existe um teto de qualidade independente de quanto compute você jogue. **Se o AVO tivesse encontrado uma variante de arredondamento incremental que fosse mais rápida, ela teria sido commitada como melhoria — e estaria numericamente errada de um jeito que o gate não vê.**

**Correção obrigatória antes de qualquer run sério:** o gate precisa comparar em precisão maior que a apresentação. Compare `Decimal` ou float com tolerância explícita **antes** do arredondamento final, e adicione um caso de teste adversarial (valores com muitas casas) que force a divergência a aparecer.

### Falha 2 — Custo de avaliação mal dimensionado

O seed levava **140s por avaliação** (5 × 27s). O paper explorou **500+ direções**. A 140s cada, isso é 19,4 horas só de avaliação — e o seed era o caso lento; após v1 caiu para 2,9s.

**Regra derivada:** dimensione o dataset para que a **avaliação do seed** fique em 5–15s, não a do candidato otimizado. Eu dimensionei pelo otimizado e o primeiro passo custou 2,3 minutos parado.

### Falha 3 — `avo submit` é sensível ao diretório

Rodar `submit` de dentro do run dir falha com `no runs found under .../runs/`. Precisa rodar da raiz do repo com `--run <path>`. Trivial, mas trava o primeiro loop de quem não sabe.

### Falha 4 — corrigir a Falha 2 revelou um problema pior: headroom concentrado

Ao reduzir o dataset para consertar o custo de avaliação, ficou visível o que os
números da §2 já diziam e ninguém tinha lido assim: **o ganho de 57,8× do v0→v1
era praticamente todo o headroom disponível.** O seed reagrupava as linhas para
cada grupo, um custo O(n×grupos); trocá-lo por um passe único resolvia o alvo. O
v2 foi rejeitado e a curva estagnou — não porque a busca falhou, mas porque não
sobrou nada para achar.

Um alvo assim é inútil para o propósito desta bancada. Todo braço de uma
ablação — com memória, sem memória, com supervisor, sem supervisor — encontra o
passe único no passo 1 e estagna junto. O experimento mediria a facilidade do
primeiro passo, não a arquitetura.

E a ablação é a razão de o laboratório existir: é a única contribuição
científica disponível (C16 no relatório de replicação — a NVIDIA declarou por
escrito que não isolou nenhum componente).

**A regra que ficou:** um alvo precisa de **3× a 8× de headroom total,
distribuído em pelo menos 4 movimentos independentes, nenhum deles valendo mais
de ~70% do ganho.** Isso não se infere lendo o código: escreva três ou quatro
versões progressivamente melhores e meça. O raciocínio completo e o caso do
`etl_agg` reconstruído estão em `docs/TARGET_DESIGN.md` §3.

Vale registrar a ironia, porque ela é instrutiva: um ganho de 57,8× parece um
sucesso retumbante do sistema. Era o sintoma de um alvo mal projetado.

## 4. Sequência para o seu caso

**Tier 0 — Python/ETL puro** ✅ *validado acima*. Custo zero, determinístico, segundos por avaliação. É onde a máquina se prova.

**Tier 0,5 — SQLite (`sql_agg`).** Degrau que não existia no plano original e
que se mostrou necessário: SQL de verdade, determinístico, sem servidor, roda no
CI. O agente evolui `query.sql` e `setup.sql` (índices são otimização legítima).
O score tensiona os dois lados — um regime frio que cobra o custo do `setup` e um
quente que só mede a consulta — para que criar índice do mundo inteiro não seja
grátis. O que se aprende aqui sobre plano de execução transfere para Postgres.

**Tier 1 — PostgreSQL (`bw_normalization`).** Próximo passo real. Score = tempo de `EXPLAIN ANALYZE` sobre snapshot congelado; gate = hash do result set ordenado. Você já tem o ambiente. Controles obrigatórios: tabela materializada como snapshot, `pg_stat_statements` para medida, e descarte da primeira execução ou cache limpo entre candidatos.

**Tier 2 — Snowflake.** Só depois do Tier 1 dar sinal. Controles não-negociáveis: `USE_CACHED_RESULT = FALSE`, warehouse de tamanho fixo com auto-suspend desligado durante o run, clone zero-copy como snapshot, score em créditos ou bytes escaneados de `QUERY_HISTORY`. Orçamento mínimo: 500 avaliações × custo por query.

## 5. Anatomia de um target (o que você escreve por alvo)

Quatro arquivos. Não é sistema novo:

1. `target.yaml` — seed, knowledge_base, entrypoint, comando `evaluate`, comando `baselines`, `score.direction`, e `agent.goal` explicando **a restrição vinculante**.
2. `eval.py` — emite `AVO_RESULT: {"correct": bool, "metrics": {...}, "error": str|null, "notes": str}` no stdout. O framework zera `primary` quando `correct=false`.
3. `seed/` — o que já funciona hoje. É o `x₀`.
4. `kb/` — DDL real, query plans, convenções. Análogo aos guias CUDA/PTX do paper.

## 6. O que NÃO fazer

- Não aponte para greenfield, decisões de arquitetura, ou qualquer coisa cuja melhoria você só avalie lendo. Sem `f`, o loop não fecha.
- Não vá para Snowflake antes do Postgres.
- Não confie num gate que você não tentou quebrar de propósito. Eu tentei e ele falhou.

## 7. Sobre "ter certeza do sucesso"

Não posso dar isso, e ninguém pode. O que este exercício mostra é o oposto: a máquina funcionou perfeitamente e **mesmo assim** meu gate de correção tinha um buraco que eu não teria descoberto sem tentar quebrá-lo.

O que dá para garantir com confiança alta:
- ✅ O harness funciona; o loop fecha; a persistência é sólida.
- ✅ `matches-or-improves` rejeita regressão corretamente.
- ✅ Um seed ingênuo é melhorado dramaticamente quando existe headroom óbvio.

O que permanece incerto:
- ❓ Se o AVO encontra otimizações que **você não encontraria** — o ganho de 57,8× aqui era óbvio para qualquer engenheiro. O teste real é num query já otimizado, onde o headroom é de 3%, não de 5000%.
- ❓ Se sobrevive ao ruído de medição de banco de dados.
- ❓ Quanto do ganho vem da arquitetura AVO versus simplesmente de um bom modelo com um número para perseguir. **Essa é a pergunta que a NVIDIA declarou não ter respondido, e é a única contribuição científica real disponível aqui.**

O próximo experimento que reduz a maior incerteza: pegar um query do `bw_normalization` que **você já otimizou à mão** e ver se o AVO bate a sua versão. Se bater, o sistema tem valor de produção. Se empatar, o valor está na ablação. Se perder, você aprendeu isso por algumas horas de CPU em vez de por um trimestre de projeto.
