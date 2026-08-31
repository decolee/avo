# Medição: em que delta acreditar, e como ler o que o avaliador devolve

## Como o número é produzido

Para cada um dos três bancos, o avaliador chama `match` uma vez, compara o
conjunto de pares devolvido com o gabarito e calcula:

```
precisão = acertos / pares devolvidos
recall   = acertos / pares do gabarito
F1       = 2 · precisão · recall / (precisão + recall)
```

O score final é a **média geométrica** dos três F1. Não há repetição e não há
mediana: F1 é exato. O mesmo código sobre os mesmos dados dá o mesmo número, ao
último decimal. Isso é uma diferença real em relação aos alvos de throughput da
bancada — aqui **não existe ruído de medição**, e qualquer delta é um delta.

O que existe no lugar do ruído é **sobreajuste**. Três bancos fixos e uma métrica
exata significam que um limiar afinado no terceiro decimal melhora o número
medido sem melhorar o linkage. Não dá para detectar isso medindo; dá para
detectar perguntando se a mudança é defensável como técnica geral. A pergunta 4
da política de commit existe exatamente para este alvo.

## A média geométrica é uma restrição, não um detalhe

Ganhar 0,05 de F1 em `pessoas` e perder 0,05 em `empresas` **piora** o score. Os
três bancos são formas de cadastro diferentes — pessoa física, razão social,
pessoa física com o dobro de ruído — e uma normalização afinada para nome
próprio não transfere para `COMERCIAL ACÁCIA LTDA`. Quando um banco regride,
diga por quê no `NOTES.md`: quase sempre é sinal de que a mudança está
explorando a forma de um dos bancos em vez do problema.

Um banco com F1 zero zera o score inteiro, porque a média geométrica é assim.

## Precisão e recall: o diagnóstico está na separação, não no F1

`notes` traz os dois separados por banco, de propósito. O F1 diz **quanto** você
errou; só a separação diz **onde**, e os consertos são opostos:

| sintoma | leitura provável | para onde olhar |
|---|---|---|
| recall baixo, precisão alta | você não está nem propondo o par | normalização, chaves de bloqueio |
| recall alto, precisão baixa | você propõe demais e aceita demais | limiar, campo corroborante, evidência contra |
| os dois medianos | comparador não distingue | similaridade e combinação de campos |
| recall travado num teto | o bloqueio não propõe o par | nenhuma comparação melhor resolve isso |

A última linha é a que mais custa tempo quando passa despercebida: se o bloqueio
não gerou o par, o comparador nunca o vê, e melhorar o comparador não move o
recall um milésimo.

## O orçamento de tempo

Todas as chamadas de `match` somam num único teto, exibido em `notes` como
`orçamento 9,6s de 14,0s`. Estourar vale **zero**, não "um pouco menos" — o
resultado é indistinguível de uma saída malformada.

Três consequências práticas:

- **O seed já gasta dois terços do teto** para fazer a coisa mais burra
  possível. Você não tem folga para colocar um comparador caro dentro do laço
  exaustivo: a conta não fecha por uma ordem de grandeza, não por uma margem.
- **Ficar mais barato é um passo legítimo mesmo com F1 igual.** A política do
  framework é "iguala ou melhora", e um passo que derruba o tempo sem mexer no
  F1 é o que torna o passo seguinte possível. Descreva-o como o que é.
- **A folga é assimétrica.** Sobrar orçamento não pontua. Se você está usando
  20% do teto, o que sobra é orçamento para um comparador melhor, e deixá-lo na
  mesa é deixar F1 na mesa.

Uma avaliação do seed custa cerca de 10 s de ponta a ponta. `./avo-eval` de
dentro do run dir mede sem tocar no lineage: use antes de submeter, sempre.

## O banco do gate não é um quarto banco

`data/gate_bank.json` tem 147 registros deformados e **não tem gabarito**. Ele
decide contrato — forma, orçamento, determinismo, pureza — e nada mais. Seu F1
nele não existe e não é medido. Se o avaliador reprovar ali, a mensagem diz qual
das quatro cláusulas caiu; ela é sobre comportamento, nunca sobre acerto.
