# Procedência

## O harness da busca não é nosso

O laço evolutivo é o upstream **`gatordevin/avo`**, fixado por commit em
`vendor/avo.lock`. Ele **não é redistribuído aqui** — tem licença própria, e o
`.gitignore` exclui `vendor/*` com uma exceção explícita para o `avo.lock`, que é
o único ponteiro versionado para o commit auditado.

`make setup` clona o upstream nesse commit. O que roda é o que foi auditado.

## O que é nosso, sob licença MIT

- `targets/` — os seis alvos: seed, avaliador, knowledge base, geradores de dados
- `labkit/` — medição, gate, mutantes, congelamento de dataset
- `experiments/` — os pré-registros, os runners, as análises e os resultados
- `docs/`, `paper/`, `tests/`

## O que é da NVIDIA, o que é do upstream, e o que é desta reprodução

`docs/AVO_REPLICATION_REPORT.md` separa isso **linha a linha**, com a fonte de
cada afirmação. Nenhum design do `gatordevin` é atribuído à NVIDIA, e nenhuma
escolha desta reprodução é apresentada como sendo do paper.

O paper original é **arXiv:2603.24517**. Este repositório é uma reprodução aberta
e independente, feita com recursos de ordens de grandeza menores, e o resultado
principal dela é negativo — ver `paper/`.

## Dados

Todos os datasets são **sintéticos e gerados por `make_data.py`**, com semente
fixa e SHA256 registrado em `dataset.lock.json`. Não há dado real de pessoa ou
empresa em lugar nenhum: os registros são da forma `cliente 00042`,
`c42@exemplo.com.br`, `+55 11 900000042`.

Os arquivos gerados não são versionados — o que é commitado é o checksum, que
torna «dataset congelado» uma afirmação verificável.

## Segurança

`SECURITY.md` descreve o risco real desta bancada, que não é vazamento de dado:
**o avaliador importa e executa código de candidato no mesmo processo**. Isso é
inerente ao que ela faz, e quem rodar deve ler aquele arquivo antes.
