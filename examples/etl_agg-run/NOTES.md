# Working notes — run de exemplo `etl_agg`

Copiado do `NOTES.md` do run. É a memória entre passos: o que foi tentado, o que
mediu, e principalmente os becos, para que um passo posterior não os re-caminhe.

## Mapa de custo, medido no passo 1

Numa linha de ~345 bytes com dezesseis campos, `json.loads` domina. O seed paga
duas vezes: constrói o registro inteiro e depois materializa uma lista por grupo,
percorrida quatro vezes (uma por campo agregado).

## Passo 1 — passe único (aceito, +65,2%)

Acumulador `[n, gross, net, last_ts]` por grupo, uma passada só. Some a
materialização e as quatro travessias. `json.loads` continua sendo o custo
dominante depois disso — foi o que apontou para o passo 2.

## Passo 2 — extração dirigida (aceito, +49,4%)

A agregação usa cinco dos dezesseis campos. Localizar cada um pela chave e
fatiar da linha evita construir os outros onze.

Escrito com busca **por nome de chave**, não por posição: a ordem dos campos no
arquivo não é contrato, e assumir posição fixa seria explorar a forma deste
dataset em vez do formato. A suposição que sobra está declarada no docstring —
chaves únicas por linha e valores sem escape em `account`/`ccy`/`status`.

## Passo 3 — REJEITADO: arredondar durante a acumulação

Hipótese: manter os acumuladores em valores de dois decimais evitaria o custo de
carregar mantissas longas.

**Rejeitado pelo gate**, e a mensagem foi exata:

```
ACC00000|BRL.gross: soma verdadeira 21424.216176, obtido 21424.23
(erro 0.0138 > tolerância 0.0050). Arredondar durante a acumulação em vez
de no final produz exatamente este desvio.
```

**Beco sem saída, não re-tentar.** Vale registrar por que isto importa: esta é
exatamente a mudança que a versão antiga do gate **aceitou como correta** (a
Falha 1 em `docs/PLANO_AVO_DATA_ENGINEERING.md` §3). Se ela tivesse medido mais
rápido, teria sido commitada e tudo depois teria sido construído em cima de um
resultado numericamente errado.

Além de errado, não era nem mais rápido: `round()` por linha custa mais do que a
aritmética que ele pretendia baratear.

## Passo 4 — busca inline (aceito, +36,3%)

Mudança de forma, não de algoritmo: a auxiliar `_field` era chamada cinco vezes
por linha. Chamada de função em Python custa mais que a busca que ela fazia.
Inline, com o espaço depois dos dois-pontos dentro do literal procurado.

## Onde ainda há espaço

Não explorado neste run: leitura em bloco com `split`, evitar `float()`/`int()`
onde o valor não é usado como número, e `bytes` em vez de `str`. O regime `wide`
está consistentemente ~20% atrás dos outros dois — muitos grupos pequenos
significam mais falhas de cache no dict e mais criação de acumulador, e nada foi
tentado nessa direção.
