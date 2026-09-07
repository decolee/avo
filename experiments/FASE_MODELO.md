# Fase Modelo — o eixo que a bancada nunca variou. Pré-registro.

**Escrito antes do primeiro dado, em 2026-09-07.** Nada acima da seção `ADENDO`
pode ser editado depois que o piloto rodar.

## Por que esta fase, e não a 2B

Os 51 runs já pagos deste laboratório rodaram **um único modelo**,
`claude-opus-5` — verificado nas transcrições, e é também o default do harness
(`vendor/avo/src/avo/config.py:13`) e o valor que o `greedy.py` cravava. O que
variou nas três execuções foi sempre o **andaime**: KB, memória, supervisor,
estrutura contra ausência de estrutura.

O placar do andaime, em três experimentos pagos:

| fase | contraste | efeito | distinguível? |
|---|---|---|---|
| ablação 1 | componentes (`sql_agg`) | −3,5% a −4,5% | não |
| 2A | `full` × `greedy` (`sql_agg`, n=11) | +4,9% | não |
| 3 | componentes (`sql_workload`, n=5) | −5,5% a +5,7% | não |

A Fase 2B repetiria o contraste de 2A com compute equiparado, por ~US$ 760. As
duas medidas que existem dele discordam por 6× (2A: +4,9%; piloto do
`sql_workload`: +32%, com n=1 no `full`), e a leitura mais provável de um
terceiro nulo é que o efeito é menor que a resolução da bancada.

**A pergunta que ninguém aqui respondeu é a do outro eixo.** Se a competência
medida vem do modelo e não da estrutura, então trocar o modelo deveria mover a
curva — e isso é verificável com a mesma infraestrutura, o mesmo alvo e o mesmo
`f`.

## O que roda no piloto

```
python3 experiments/ablacao/piloto.py --alvo sql_workload --modelo <M>
```

Um piloto por modelo, para estimar **cv e tamanho de efeito** antes de comprar
o experimento. Não é o experimento; é o que decide se o experimento é pagável.

## Hipótese, declarada antes

Diferenças entre modelos neste alvo são **maiores** que as de andaime — da ordem
de 15% ou mais, portanto detectáveis com n=5 dado o cv de 8,5% do alvo.

**Isto é hipótese, não medida.** É exatamente o tipo de suposição que a Fase 2A
fez sobre o andaime (5%) e que custou US$ 290 para descobrir errada. O piloto
existe para não repetir isso.

## Critério de decisão, fixado aqui

Do piloto sai `n` para o efeito observado, por `n ≈ 2·(2,8·s/Δ)²`. Então:

- **n ≤ 8 por braço** → o experimento é pagável; rodar 3 modelos × n.
- **8 < n ≤ 20** → pagável só para 2 modelos (os extremos da escala).
- **n > 20** → **não rodar.** Registrar que o eixo do modelo também está abaixo
  da resolução desta bancada, que é um resultado, e parar.

O terceiro caso é o que a disciplina daqui existe para tornar possível dizer.

## Desvios declarados

**1. O piloto não é o experimento.** Nenhum número dele entra em análise —
mesma regra do piloto da Fase 1. Ele só dimensiona.

**2. O `--modelo` do `runner.py` é código novo.** Foi adicionado em 2026-09-07;
antes disso o runner não repassava modelo nenhum e o harness usava o default
dele. O default é `claude-opus-5`, idêntico ao que o `greedy.py` cravava, então
a mudança é comportamentalmente neutra para tudo que já rodou — os braços batiam
por coincidência documentada e agora batem por construção. Verificado antes de
declarar.

**3. Orçamento igualado por PASSOS, não por tokens.** Herda a limitação da Fase 3
e ela é **pior aqui**: modelos diferentes gastam tokens e relógio muito
diferentes pelos mesmos 8 passos. Um resultado a favor do modelo mais caro é, em
parte, um resultado sobre orçamento. O custo por braço será reportado, e a
leitura tem que ser feita com isso à vista.

**4. O que este eixo NÃO responde.** Nada sobre AGI, nem sobre capacidade geral.
O alvo é otimização de consultas SQL com `f` objetivo e verificável. É a classe
de problema em que o loop fecha — e, por construção, a classe em que a pergunta
interessante sobre generalidade **não** pode ser feita. Ver `CLAUDE.md`,
"O que não fazer".

## Análise, fixada aqui

Idêntica à da Fase 3: bootstrap com 10.000 reamostragens para o intervalo de cada
diferença, Holm-Bonferroni sobre as comparações, `destilar_logs` rodado antes,
efeito e intervalo sempre reportados.

---

## ADENDO 2026-09-07 — o piloto rodou e mudou o desenho

Resultado completo em `PILOTO_MODELO_RESULTADO.md`. Em uma linha: o eixo do
modelo move **27,5%**, cinco vezes mais que o maior contraste de andaime já
medido nesta bancada, e o critério de parada (`n ≤ 8`) deu **0,2** — pagável.

**Mas o desenho pré-registrado não é mais o certo, e o motivo estava no desvio 3.**

Pelos mesmos 8 passos o Opus gastou US$ 25,18 e o Sonnet US$ 5,53 — 4,6× mais
dinheiro. O efeito de 27,5% está confundido com orçamento, exatamente como
declarado antes do dado. Rodar 3 modelos × n=5 a 8 passos mediria o mesmo
contraste confundido com mais precisão.

**O desenho passa a ser:** igualar por dólar, não por passos. O Sonnet recebe ~36
passos contra os 8 do Opus (US$ 3,15/passo contra US$ 0,69), n=3, ~US$ 75 e ~7 h,
com o braço do Opus já pago. A pergunta vira decidível: *com orçamento igual, o
Sonnet alcança os 7,4×?*

Risco declarado agora, antes de rodar: o alvo tem 8 movimentos medidos e 36 passos
podem esgotá-lo. Se o Sonnet platôa, é preciso distinguir platô por falta de alvo
de platô por falta de capacidade — o passo do platô será comparado com o do Opus.

Mudar o desenho depois do piloto é o que o piloto existe para permitir (desvio 1:
"ele só dimensiona"). O que não pode mudar depois do **experimento** é a análise,
e ela segue fixada: bootstrap 10.000, Holm-Bonferroni, `destilar_logs` antes.

**Não rodado nesta sessão.** A decisão de gastar é de quem paga.
