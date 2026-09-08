# O andaime não paga — o paper

`index.html` é o artigo completo: quatro experimentos controlados sobre a
contribuição dos componentes do AVO em engenharia de dados, com as figuras
desenhadas na escala dos dados.

Publicado como artifact: https://claude.ai/code/artifact/b698a839-c782-40c3-9542-7fb7f3795e01

## De onde sai cada número

| seção | fonte |
|---|---|
| §03 melhoria do loop | `experiments/ablacao/resultados/*/results.jsonl` |
| §04 Fig. 1 (floresta) | as três `results.jsonl` + `fase2_sql_agg/greedy.jsonl` |
| §05 Fig. 2 e 3 | `resultados/remedido_modelo.jsonl` e `dolar_sonnet_36p/piloto.jsonl` |
| §06 custos | soma de `custo_usd` sobre os passos de cada arquivo |
| §07 Fig. 4 | `remedido_modelo.jsonl`, colunas `seed_original` e `seed_remedido` |

Os relatórios longos de cada experimento, com o pré-registro e os desvios
declarados, ficam em `experiments/`:

- `ABLACAO_RESULTADO.md` — a ablação de componentes
- `EIXO_MODELO_RESULTADO.md` — o eixo do modelo
- `DEFEITOS.md` — os 18 defeitos de instrumento
- `FASE_MODELO.md`, `ABLACAO_SQL_WORKLOAD.md` — os pré-registros

## O enquadramento, e por que ele é este

O resultado principal é **negativo**: três experimentos e US$ 976 não
distinguiram nenhum componente do AVO do ruído. O artigo diz isso na primeira
linha do resumo, declara a potência da bancada, e calcula o preço da resposta
que não foi comprada (n≈41, US$ 1.889 por par de braços).

Um artigo que tentasse provar que o AVO funciona desmontaria no primeiro leitor
que abrisse o `results.jsonl`. O que sustenta este é outra coisa: **ninguém
publicou uma comparação controlada do AVO** — nem a NVIDIA, cujo próprio post diz
que seus números "não devem ser interpretados como medida direta da contribuição
de performance do AVO". Um nulo bem medido, com o poder declarado, é a
contribuição.
