# `pg_normalize` — Tier 1, PostgreSQL

**Estado: ANDAIME. Não é um alvo válido ainda, e o `avo-lab verify` o recusa.**

Este diretório existe porque a Sessão 6 do `docs/RUNBOOK.md` pede o Tier 1 e o
container onde as sessões rodaram **não tem como executá-lo**. Em vez de fingir
que rodou, fica registrado o que falta e o que já está pronto.

## Por que não rodou aqui

Verificado, não suposto:

| requisito | estado |
|---|---|
| cliente `psql` | presente |
| servidor `postgres` / `initdb` | **ausentes** |
| driver `psycopg2` | instalável (`pip install psycopg2-binary` funciona) |
| servidor em `127.0.0.1:5432` | **nada escutando** |
| daemon do Docker | **indisponível** (`docker info` falha) |

Sem servidor e sem como subir um, não há o que medir. Um alvo cujo `f` não roda
não é um alvo — é uma intenção.

## O que muda em relação ao `sql_agg`

O `sql_agg` (SQLite) foi construído como a ponte para cá, e a maior parte
transfere: o contrato do result set, o gate por comparação linha a linha, a
tensão entre regime frio e quente, a recusa de DDL na consulta e de tabela
materializada no setup.

O que **não** transfere, e é o trabalho real deste alvo:

- **Cache do servidor.** O SQLite abre uma cópia nova do arquivo a cada
  execução. O Postgres tem `shared_buffers` e cache do SO que sobrevivem entre
  consultas, então "frio" e "quente" deixam de ser controláveis pelo mesmo
  truque. Ou se descarta a primeira execução, ou se usa `pg_stat_statements`,
  ou se reinicia o servidor entre candidatos — cada opção mede uma coisa
  diferente e a escolha precisa estar declarada na KB.
- **Snapshot congelado.** O equivalente do `dataset.lock.json` é uma tabela
  materializada restaurada de um dump, com checksum do dump versionado.
- **Estatísticas do planejador.** `ANALYZE` muda o plano; sem controle explícito
  o mesmo candidato mede diferente em execuções diferentes.
- **Concorrência.** Um servidor compartilhado com qualquer outra carga torna a
  medição inútil. O alvo precisa recusar-se a rodar se detectar outra sessão
  ativa.

## Como colocar para funcionar

1. Suba um Postgres 16 dedicado, sem outra carga.
2. `pip install psycopg2-binary`.
3. Exporte `PG_NORMALIZE_DSN` apontando para ele.
4. Escreva `make_data.py` para gerar e dumpar o snapshot; commite o checksum.
5. Adapte o `eval.py` do `sql_agg`, resolvendo os quatro pontos acima e
   declarando cada decisão na KB.
6. Meça a escada e declare `lab.headroom_medido` no `target.yaml`. Sem isso o
   `avo-lab verify` recusa — como recusa hoje.

## O experimento que vale mais que este alvo

`docs/ABLATION_PROTOCOL.md` §9: pegue uma query do `bw_normalization` que você
**já otimizou à mão** e veja se o AVO bate a sua versão. Os três desfechos
possíveis — bate, empata, perde — são todos informativos, e o experimento
responde uma pergunta de produção que nenhum alvo sintético responde.
