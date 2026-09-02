# ABLATION — `csv_normalize`, 2026-09-01

**Pré-registro:** `docs/ABLATION_PROTOCOL.md`. A métrica primária, o n, o método
de análise e o efeito mínimo detectável foram fixados **antes** de rodar, e a
análise abaixo é escrita contra eles.

**Execução:** 16 runs · 48 passos de agente · 12,2 h · US$ 168,19
**Modo:** não supervisionado (`avo run --backend claude_cli`), um agente novo por
passo, sem o conhecimento de quem escreveu o alvo.

---

## 1. Resultado primário

Melhoria relativa (`primary_final / primary_seed`), n = 4 por braço.

| braço | média | mediana | Δ vs `full` | IC 95% (bootstrap) | p Holm | distinguível? |
|---|---|---|---|---|---|---|
| `full` | 4,91 | 4,77 | — | — | — | — |
| `no_supervisor` | 5,15 | 5,05 | +0,25 | [−0,20, +0,63] | 0,738 | **não** |
| `no_kb` | 5,10 | 5,29 | +0,19 | [−0,53, +0,80] | 0,738 | **não** |
| `no_memory` | 5,26 | 5,26 | +0,35 | [−0,12, +0,75] | 0,594 | **não** |

**Nenhuma diferença é distinguível do ruído.** Todos os intervalos cruzam zero.

**Efeito mínimo detectável com n = 4: 0,611.** A maior diferença observada é
0,350 — pouco mais da metade do que este desenho consegue separar. O experimento
está subdimensionado para os efeitos presentes, e isso era previsível: o
pré-registro (§6) já dizia que n = 5 detectaria apenas efeitos da ordem de 30%.

> **"Não distinguível do ruído" não é "não existe".** As duas frases aparecem
> separadas neste documento de propósito, e nenhuma conclusão troca uma pela
> outra.

---

## 2. O achado que invalida metade do experimento

Os três braços com supervisor habilitado somam **36 passos**. O supervisor
**disparou em zero deles**.

A causa é aritmética: `stagnation_window = 3` exige três passos consecutivos sem
nova melhor versão, e cada run tem **três passos no total**. Com a taxa de
aceitação observada (43 de 48 passos aceitos), a condição de estagnação é
inalcançável dentro do orçamento de passos que eu escolhi.

**Consequência: o braço `no_supervisor` é idêntico ao `full` por construção.** A
diferença de +0,25 entre eles não é um efeito pequeno — é uma medida direta do
ruído entre dois braços que executam exatamente o mesmo código. Isso é útil: dá
uma estimativa empírica do piso de ruído deste desenho, **+0,25 em unidades de
melhoria relativa**, o que confirma que os outros dois deltas (+0,19 e +0,35)
estão dentro dele.

O mesmo problema atinge o `no_memory` de forma mais branda. Ele apaga o
`NOTES.md` entre passos, então só difere do `full` **a partir do passo 2** — e os
passos 2 e 3 contribuem, em média, apenas 1,15× e 1,13×. A janela em que a
ablação tem efeito é minúscula.

Só o `no_kb` foi genuinamente ablacionado do primeiro passo ao último.

---

## 3. A forma da curva explica o resto

Melhoria acumulada média sobre o seed, por passo:

| braço | passo 1 | passo 2 | passo 3 | ganho do passo 2 | ganho do passo 3 |
|---|---|---|---|---|---|
| `full` | 4,44 | 4,57 | 4,91 | 1,03× | 1,07× |
| `no_kb` | 4,23 | 4,73 | 5,10 | 1,12× | 1,08× |
| `no_memory` | 4,09 | 4,68 | 5,26 | 1,15× | 1,13× |
| `no_supervisor` | 4,05 | 4,76 | 5,15 | 1,21× | 1,09× |

**O primeiro passo captura ~85% do ganho total em todos os braços.** E é
exatamente o passo em que os braços são mais parecidos entre si: não há lineage
para consultar, não há `NOTES.md` acumulado, e o supervisor não teria como ter
disparado.

Um experimento de três passos num alvo cujo primeiro movimento vale 4× não mede
arquitetura. Mede a qualidade do primeiro chute — e essa é a mesma em todos os
braços por construção.

---

## 4. O que deu certo no desenho

**A catraca de ruído não mordeu.** O pré-registro (§5b) previa que um agente que
falha deixa a árvore intacta e a política *iguala-ou-melhora* commita a versão
por ruído de medição, inflando os braços que falham mais. O runner registrou
`codigo_mudou` por passo, e o resultado foi limpo:

| braço | aceitos | com código novo | catracas de ruído |
|---|---|---|---|
| `full` | 9 | 9 | **0** |
| `no_kb` | 11 | 11 | **0** |
| `no_memory` | 12 | 12 | **0** |
| `no_supervisor` | 10 | 10 | **0** |

Zero em 42 aceites. A mitigação era necessária de qualquer forma — sem a coluna
eu não saberia disso, saberia apenas que não vi.

**Falhas de agente ficaram equilibradas.** Uma falha real (`no_kb`) e cinco
passos mortos por timeout, distribuídos. Nenhuma comparação precisou ser marcada
como não interpretável.

**Intercalação e ordem aleatorizada funcionaram.** Os braços rodaram alternados,
com ordem sorteada por rodada. A deriva de máquina, se houve, se distribuiu.

---

## 5. Desvios do pré-registro

Declarados, com o motivo:

| desvio | pré-registrado | executado | por quê |
|---|---|---|---|
| braços | 6 | 4 | `no_lineage` e `greedy` exigem cirurgia no prompt dentro do harness, que é vendorizado num commit fixo. Modificá-lo quebraria a reprodutibilidade que o lock existe para garantir |
| n por braço | 5 | 4 | orçamento: o desenho completo custaria 54 h e US$ 958 |
| passos por run | — | 3 | idem. **Foi o desvio mais custoso** — ver §2 |
| esforço do agente | não fixado | `medium` | igual em todos os braços; baixar o nível absoluto não altera a comparação e foi o que fez caber n suficiente |
| alvo | `etl_agg` | `csv_normalize` | o verificador de headroom mostrou que o `etl_agg` caiu para 1,61× depois do endurecimento do gate da Sessão 2, e um alvo que não discrimina desperdiçaria as 12 h |
| orçamento por passo | igualado | **não igualado** | `--max-budget-usd` não é respeitado pelo harness: passos custaram até US$ 5,79 com teto declarado de US$ 3,00. Os custos por braço saíram desiguais (US$ 32 a US$ 47) |

O último desvio é o mais sério para a validade: o pré-registro (§4) chama o
orçamento igualado de controle **não negociável**, e ele não foi cumprido. O
braço `no_kb` gastou 30% menos que o `no_memory`. Como nenhuma diferença é
distinguível, isso não muda a conclusão — mas mudaria se alguma fosse.

---

## 6. Conclusão

**Este experimento não responde à pergunta que ele foi desenhado para
responder.** Com três passos por run, o primeiro movimento captura 85% do ganho,
os braços são quase idênticos nesse movimento, e o supervisor nunca chega a
existir. O que sobrou foi uma medição do ruído do desenho.

O que ele **estabelece**:

1. O piso de ruído deste desenho é ~0,25 em melhoria relativa, medido entre dois
   braços que sabidamente executam o mesmo código.
2. A catraca de ruído, que era a ameaça mais séria à métrica de commits aceitos,
   não ocorreu — e agora há instrumentação para saber disso em vez de supor.
3. O custo real de uma ablação séria nesta bancada: **US$ 3,5 e 15 min por passo
   de agente**. O desenho pré-registrado completo custa ~US$ 958 e 54 h.

O que ele **não** estabelece: nada sobre a contribuição de memória, KB ou
supervisão. A direção observada (braços ablacionados ≥ completo em todos os três
casos) é curiosa e vale registrar como hipótese, mas com n = 4, IC cruzando zero
e um braço nulo por construção, tratá-la como resultado seria exatamente o erro
que este documento existe para não cometer.

---

## 7. O próximo experimento, corrigido

As três correções, em ordem de importância:

1. **Passos por run ≥ 12, e `stagnation_window` ≤ 3.** Sem isso o supervisor não
   existe e a memória quase não existe. Este é o conserto que mais importa.
2. **Alvo com headroom que não se esgote no passo 1.** O `csv_normalize` entrega
   4× no primeiro movimento; a partir daí a trajetória é rasa. Um alvo cujo
   primeiro passo valha ~1,5× deixaria os passos seguintes carregarem sinal.
3. **Orçamento igualado de verdade**, contando tokens por braço e truncando o
   que exceder — já que o `--max-budget-usd` do harness não segura.

Com 4 braços × 5 seeds × 12 passos a US$ 3,5 por passo, isso é **US$ 840 e
~50 h**. É o preço de responder a pergunta, e é bom sabê-lo antes de prometer a
resposta.

Uma alternativa mais barata que vale considerar antes: rodar `full` contra
`greedy` apenas — o braço de controle honesto da §3 do protocolo, que compara a
máquina inteira contra "o mesmo modelo com o mesmo `f` e nenhuma estrutura". Se
esses dois empatarem, a pergunta sobre componentes individuais fica menos
interessante, e a resposta sai por um sexto do custo.

---

## 8. O que aconteceu depois: o controle rodou, e ele explica este documento

A alternativa mais barata sugerida no fim da §7 foi executada.
`experiments/CONTROLE.md` tem o desenho e os números; o resumo é que **`full` e
`greedy` empataram**, e a razão do empate reescreve a leitura deste relatório.

O resultado é: uma sessão de agente **morta aos 106 segundos**, custando
**US$ 0,53**, mede **4,55×** no `csv_normalize`. O AVO completo, com 23× mais
relógio e 22× mais dinheiro, mede 4,92×. Sobre o ganho disponível, a sessão de
cem segundos captura **68% sozinha**.

**Isto muda o diagnóstico da §5.** Ali eu atribuí o resultado nulo desta ablação
a n pequeno e a trajetórias rasas — e a §7 receitou mais passos e mais sementes.
As duas coisas continuam verdadeiras, mas nenhuma delas era a causa raiz. A causa
raiz é que **o alvo não tinha espaço onde os braços pudessem diferir**. Nenhum
número de sementes conserta isso: os quatro braços estavam disputando os 30% de
headroom que sobram depois que qualquer agente pega os 70% fáceis, e o desvio de
medição é maior que o que restou para disputar.

Isso virou a oitava propriedade de um alvo válido — `docs/TARGET_DESIGN.md` §3e —
com uma sonda que a mede por US$ 0,50 e uma checagem no `avo-lab verify` que a
cobra. Com ela ligada, **o `csv_normalize` deixa de ser apto para ablação**, e
este relatório passa a ser o registro de um experimento rodado num alvo que a
bancada hoje recusaria.

**A receita da §7, corrigida.** O item 2 estava certo pelo motivo errado. Não
basta "headroom que não se esgote no passo 1": é preciso **headroom que uma
sessão única não esgote em cem segundos**. É uma barra muito mais alta, e nenhum
dos cinco alvos deste repositório a alcança — o que é o achado mais acionável que
saiu de US$ 343 de experimento.

Os itens 1 e 3 permanecem de pé, e continuam valendo US$ 840. Mas gastá-los antes
de ter um alvo que passe na §3e seria comprar de novo o mesmo intervalo que
contém zero.

---

## 9. Correção: os agentes deste experimento também estavam cegos

O mesmo defeito de permissão descrito em `CONTROLE.md` afetou esta ablação. Os
agentes rodaram com `--permission-mode acceptEdits` e sem `--allowed-tools`, e
não conseguiam executar `./avo-eval` de dentro do passo.

**O que isso muda aqui é menos do que parece, e vale explicar por quê.** O
`full` não perdeu o feedback: o harness avalia e gateia a cada passo, então o
laço continuou recebendo o número — o que se perdeu foi a medição DENTRO do
passo, o "criticar e verificar" do abstract do paper (C2). Cada passo foi
"proponha no escuro, o harness mede depois, o gate aceita ou rejeita".

Isso vale igualmente para os quatro braços, então a comparação entre eles
continua sendo entre iguais e o resultado nulo de §1 permanece. O que não
permanece é a caracterização: este experimento não ablacionou "o AVO", e sim uma
versão dele em que o operador de variação não pode verificar o próprio trabalho.

E há uma leitura nova que o defeito abre. A §5 registrou que o primeiro passo
captura ~85% do ganho e que a trajetória depois é rasa. Com agentes cegos, isso
tem uma explicação mecânica óbvia que não estava disponível antes: sem poder
medir, o agente aplica o que a KB ensina, e não há como refinar o que não se
consegue cronometrar. **Um agente que enxerga pode ter trajetória diferente**, e
saber disso é o motivo de o experimento precisar ser refeito antes de qualquer
conclusão sobre componentes.
