# Como projetar um alvo que serve para alguma coisa

O harness é a parte fácil e já está resolvida. O que decide se este laboratório
produz conhecimento ou ruído é o alvo — e especificamente a função `f`. Este
documento é o que aprendemos construindo os quatro alvos atuais, incluindo os
erros que cometemos e que agora estão travados por teste.

A regra que resume tudo: **o loop pode rodar sem você; a definição de `f` não.**
Quando `f` está errado, o agente não trava — ele fica confiante.

---

## As cinco propriedades de um alvo válido

Um alvo precisa das cinco. Faltando qualquer uma, ele produz números que
parecem resultado e não são.

| # | propriedade | como se verifica |
|---|---|---|
| 1 | O gate tem mordida | `--selftest` verde, ≥ 5 mutantes rejeitados |
| 2 | O custo está dimensionado | `--budget` verde |
| 3 | O headroom é graduado | medido à mão; ver §3 |
| 3b | A medição não é trapaceável | candidato memoizador não pontua; ver §3b |
| 4 | O score é diagnóstico | ≥ 2 regimes que são *formas* de dado diferentes |

Quatro saíram de falhas reais desta bancada. A última saiu do guia de targets do
upstream e é a mais barata de acertar.

Vale notar a ordem em que foram descobertas: 1 e 2 na primeira execução, 3 ao
corrigir 2, e **3b depois de o alvo já ter sido declarado pronto**. Cada correção
expôs a seguinte. É a razão de a checklist do fim deste documento existir.

---

## 1. O gate tem mordida — ou: o erro que quase não vimos

**O que aconteceu.** A primeira versão do `etl_agg` usava o mesmo dataset para
medir tempo e para julgar correção. Submetemos de propósito uma versão que
arredonda `gross`/`net` a cada acumulação em vez de no final — uma violação
direta do contrato. **O gate aceitou como correta.** Ela só foi rejeitada porque
ficou mais lenta.

**Por que passou.** Os `amount` do dataset de performance já tinham duas casas
decimais. O erro de ponto flutuante acumulado ficava abaixo do limiar de
`round(x, 2)`, e a divergência dava exatamente zero. Um dataset com duas casas é
*estruturalmente incapaz* de expor arredondamento incremental.

**Por que isso importa mais do que parece.** É o teto de verificadores
imperfeitos de *Inference Scaling fLaws* (arXiv:2411.17501): com falsos
negativos no verificador, existe um teto de qualidade independente de quanto
compute você jogue. Se a busca tivesse encontrado uma variante de arredondamento
incremental **mais rápida**, ela teria sido commitada como melhoria — e estaria
numericamente errada de um jeito que o gate não vê. Cada versão seguinte seria
construída em cima dela.

**As regras que ficaram.**

- **Separe os datasets.** O que decide `correct` é pequeno, adversarial, e nunca
  é o que mede tempo. São requisitos opostos: o benchmark quer volume e
  regularidade, o gate quer casos difíceis e patológicos.
- **Compare contra a verdade, não contra outra implementação.** No `etl_agg` a
  referência soma com `math.fsum` — a soma exatamente arredondada — e o gate
  aceita meio centavo mais uma folga proporcional à magnitude do grupo.
  Arredondamento incremental erra por centésimos e é pego; a ordem em que você
  somou erra por 1e-10 e passa. O gate julga a lógica, não a aritmética.
- **Escreva os mutantes primeiro.** Cada mutante é o atalho plausível que um
  otimizador de verdade tentaria, não um bug absurdo. Se você não consegue
  imaginar cinco jeitos plausíveis de estar errado, você não entendeu o problema
  o suficiente para julgá-lo.
- **Prove que o dataset tem dentes.** Os geradores têm uma asserção que se recusa
  a escrever um dataset de gate incapaz de separar o certo do errado. É a Falha 1
  virada em código: veja `_assert_dataset_has_teeth` em
  `targets/etl_agg/make_data.py`.

Um gate que nunca foi atacado não é um gate, é uma esperança.

---

## 2. O custo está dimensionado

**O que aconteceu.** O seed do `etl_agg` levava 93 s por execução nesta máquina.
Com cinco repetições, **7,8 minutos por avaliação**. O paper explorou 500+
direções; a esse custo seriam 65 horas só de medição.

**A causa.** Dimensionamos o dataset pelo candidato otimizado, que rodava em
0,5 s. O seed era o caso lento e ninguém mediu o seed.

**A regra.** Dimensione pela avaliação do **seed**, não pela do candidato:

- **Teto:** uma avaliação completa do seed em **≤ 25 s**. Acima disso cada passo
  do agente vira espera.
- **Piso:** a execução medida mais rápida imaginável em **≥ 20 ms**. Abaixo
  disso a variação do escalonador fica comparável à melhoria e a busca passa a
  perseguir ruído.

Os dois números medem coisas diferentes e falham por motivos opostos: o teto
protege o tempo do agente, o piso protege o sinal. `evalkit.budget_report`
verifica os dois e `--budget` é obrigatório em todo alvo.

---

## 3. O headroom é graduado — a que mais custa acertar

**O que aconteceu.** Depois de corrigir a Falha 2 reduzindo o dataset,
descobrimos um problema pior. O seed original reagrupava as linhas para cada
grupo, um custo O(n×grupos). Substituí-lo por um passe único dava **57,8×** de
ganho. Medido nesta máquina, o headroom total do alvo era **132×**.

Parece ótimo. É inútil.

**Por quê.** Um alvo em que o primeiro movimento óbvio captura 98% do ganho
disponível não consegue distinguir nada. Todo braço de uma ablação — com
memória, sem memória, com supervisor, sem supervisor — encontra o passe único no
passo 1 e depois estagna junto. O experimento mede a facilidade do primeiro
passo, não a arquitetura.

E a ablação é o motivo de o laboratório existir: a NVIDIA publicou uma
arquitetura com cinco componentes, declarou que dois são "particularmente
importantes", e **admitiu por escrito que não mediu a contribuição individual de
nenhum** (C16 no relatório de replicação). Um alvo que não discrimina joga fora a
única contribuição científica disponível.

**A forma que se quer.** O paper mede 40 versões em 7 dias com cinco pontos de
inflexão arquitetural, melhoria em **saltos discretos separados por platôs**, e
retornos decrescentes claros. Um alvo bom reproduz essa forma em miniatura:

> **3× a 8× de headroom total, distribuído em pelo menos 4 movimentos
> independentes, nenhum deles valendo mais de ~70% do ganho.**

**Como o `etl_agg` chegou lá.** Duas mudanças de projeto:

1. O seed passou a ser *plausivelmente ingênuo* em vez de catastrófico —
   materializa linhas e listas por grupo, mas não é O(n×grupos). Headroom do
   passe único caiu de 57,8× para 1,5×.
2. O registro ficou **largo**: dezesseis campos, como um extrato de ledger de
   verdade, enquanto a agregação precisa de cinco. Isso cria um segundo eixo
   independente — `json.loads` materializa tudo, e parsing dirigido é uma
   otimização legítima e de peso.

Medido depois da mudança:

| versão | geomean | vs seed |
|---|---|---|
| v0 seed | 4,16 | 1,00× |
| v1 passe único, acumulador em lista | 7,02 | 1,69× |
| v2 extração dirigida dos campos | ~13,6 | ~3,3× |

Nenhum movimento sozinho domina, e ainda sobra espaço abaixo. É a diferença
entre um alvo que mede arquitetura e um que mede sorte no primeiro passo.

**Como verificar.** Não dá para inferir: escreva você mesmo três ou quatro
versões progressivamente melhores e meça o geomean de cada. Se um movimento
captura mais de 70%, reprojete. É meia hora de trabalho que decide se o alvo
serve.

---

## 3b. O gate de correção não pega trapaça de medição

Descoberto atacando o `etl_agg` depois de já considerá-lo pronto — e é a falha
mais sutil das que encontramos, porque **o candidato está correto**.

**O ataque.** Um candidato que memoiza a saída indexada pelo caminho do arquivo:

```python
_CACHE = {}
def transform(path):
    if path in _CACHE:
        return _CACHE[path]          # da segunda chamada em diante, microssegundos
    ...
```

O avaliador chama a função várias vezes por regime para tirar a mediana. A
primeira chamada faz o trabalho; as outras devolvem o resultado pronto.

Medido: **4.672.896** contra 4,16 do seed. Um milhão de vezes "melhor", sem uma
única otimização.

**Por que nenhum gate de correção pega isso.** O resultado devolvido está certo.
Todos os mutantes continuam sendo rejeitados. O `--selftest` fica verde. A
correção e a medição são eixos independentes, e um gate perfeito no primeiro não
diz nada sobre o segundo.

**A defesa, em três camadas.** Cada uma fecha o que a anterior deixa passar, e
foi preciso descobrir as três — cada correção expôs o próximo ataque.

1. **Caminho novo a cada execução.** Um symlink com nome diferente apontando
   para o mesmo conteúdo custa microssegundos e faz um cache indexado por
   caminho errar sempre (`evalkit.unique_alias`).
   *Ainda passa:* cache indexado pelo **conteúdo** — mediu 10× o ótimo honesto.
2. **Módulo novo a cada execução.** `measure(..., fn_factory=...)` reimporta o
   candidato antes de cada execução medida, então nenhum estado de módulo
   sobrevive. Derruba qualquer memoização em processo — por caminho, por
   conteúdo, por `lru_cache` —, não só a que você antecipou.
   *Ainda passa:* cache em **disco**, que não é estado de módulo.
3. **Proibição de escrever em disco durante a medição.**
   `evalkit.no_disk_writes` intercepta `builtins.open`, `io.open` e `os.open`
   e recusa qualquer abertura para escrita. Duas sutilezas que valem manter: a
   violação é **anotada antes** de a exceção subir, então um candidato que
   embrulhe o `open` em `try/except` não apaga o registro — só deixa de saber
   que falhou; e `.pyc`/`__pycache__` são liberados, porque um `import` tardio
   dentro da função medida grava bytecode e reprovar por isso seria reprovar
   candidato honesto.

O custo das três somadas é de microssegundos por execução. O único efeito real é
que trabalho feito no import passa a ser cobrado em toda execução, o que é justo:
compilar uma regex custa microssegundos, e um candidato que faz algo caro no
import está movendo trabalho para fora da medição.

A camada 3 veio do gate do `dedupe_match`, que precisava dela por outro motivo —
impedir a leitura do gabarito — e generalizou bem. Leitura continua livre nos
alvos de throughput, porque ali ler o arquivo de entrada é exatamente o trabalho.

Há ainda uma quarta verificação, de natureza diferente: `evalkit.read_floor` /
`implausible_speed` rejeitam uma execução mais rápida que ler o próprio arquivo
de entrada. É um limite **físico**, não uma barreira — não impede nada, só
constata que quem foi mais rápido que a leitura não leu. Serve de rede para o
que as três camadas não cubram, e vale saber que é uma rede de malha larga: os
pisos medidos ficam entre 0,3 ms e 1,5 ms contra execuções honestas de 60 ms a
450 ms, então ela só pega o absurdo. Um cache indexado por hash do conteúdo paga
a leitura e passou por ela marcando 10× o ótimo honesto — foi a camada 2 que o
pegou, não esta.

**O desfecho, depois da defesa:**

| candidato | resultado | leitura |
|---|---|---|
| seed | 3,6 | referência |
| memoização por caminho | 6,1 | igual à versão honesta que ele embrulha |
| memoização por conteúdo | 5,2 | **pior** que a honesta: paga o hash e não recebe nada |
| cache em disco | **reprovado** | "escreveu em /tmp/etl_cache_8ec4c15a.json" |
| candidato otimizado honesto | 13,2 | o ganho real |

Trapacear passou de valer um milhão a custar caro. É a propriedade que se quer:
não é que a trapaça seja proibida, é que ela deixa de compensar.

**O que ainda não é coberto.** Só as portas de arquivo do CPython são
interceptadas. Código que abra arquivo por dentro de C — `sqlite3.connect`, por
exemplo — passa pela camada 3. Fecha-se o caminho fácil, não todos.

A defesa completa contra qualquer cache seria **dados diferentes a cada
execução**: N variantes por regime, mesma forma, bytes diferentes. Isso
multiplicaria o dataset por 5 (dezenas ou centenas de MB) para fechar um resíduo
que já exige um ataque deliberado, contra uma regra escrita na KB, visível no
diff. Se um alvo futuro precisar — um que rode sem supervisão por dias, digamos —
o caminho é gerar as variantes e rotacioná-las por `Regime.args_factory`, que já
aceita isso sem mudança no `labkit`. A decisão de não fazer agora é uma troca
declarada, não um descuido.

**A regra.** Toda medição repetida é uma superfície de ataque. Antes de declarar
um alvo pronto, escreva o candidato trapaceiro e rode-o. Se ele pontuar, o alvo
está quebrado — e, ao contrário de um gate furado, nada no `--selftest` vai
avisar.

---

## 4. O score é diagnóstico

**Regimes são formas de dado, não repetições do mesmo dado.** A versão antiga do
`etl_agg` reportava `cold`, `best` e `median` — o mesmo benchmark medido três
vezes. Isso não diagnostica nada: as três sobem juntas, e nenhuma diz *onde* a
mudança ajudou.

Os regimes atuais são formas diferentes: muitos grupos pequenos, poucos grupos
grandes, volume concentrado. Uma otimização que só ajuda quando os grupos cabem
no cache aparece num regime e some no outro — e é isso que torna o número
diagnóstico.

**A média geométrica é uma restrição, não um detalhe.** Ganhar 20% num regime e
perder 20% em outro *piora* o score. Isso empurra a busca para transformação
geral em vez de truque específico, que é exatamente o que se quer.

**Mediana, nunca melhor-de-N.** O melhor-de-N recompensa variância: a maneira
mais barata de melhorar o melhor-de-N é rodar mais vezes, não ficar mais rápido.

**Dê ao agente uma baseline real.** "Mais rápido que o seed" é um alvo fraco;
"mais rápido que a implementação que qualquer um escreveria" é o enquadramento
do paper e é muito melhor. O `etl_agg` mede a referência de passe único como
baseline: o seed marca 4,16 e a baseline 6,21, então o agente sabe desde o passo
1 que há alguém a bater.

---

## Checklist para um alvo novo

```
[ ] target.yaml carrega, evaluate.command é lista, score.direction válido
[ ] seed/ é correto e obviamente subótimo — e PASSA no próprio gate
[ ] kb/ ensina o domínio e NÃO entrega a solução
[ ] make_data.py é determinístico e grava dataset.lock.json
[ ] o gerador se recusa a escrever um dataset de gate sem mordida
[ ] >= 5 mutantes plausíveis; --selftest verde
[ ] --budget verde (seed <= 25s, execução mais rápida >= 20ms)
[ ] headroom medido: >= 4 movimentos, nenhum > 70% do ganho
[ ] >= 2 regimes que são formas de dado diferentes
[ ] baseline real, não só o seed
[ ] a medição usa caminho novo E módulo novo por execução (anti-memoização)
[ ] tentei trapacear no meu próprio alvo e não consegui
```

O último item não é retórica. Escreva um candidato que cacheia a saída entre
chamadas, um que detecta qual arquivo está lendo, um que memoriza o resultado.
Rode. Se algum pontuar, o alvo está quebrado, e é melhor descobrir agora do que
depois de quarenta versões construídas em cima. No `etl_agg` isso rendeu a §3b —
achada depois de o alvo já ter sido dado como pronto, com `--selftest` verde e
tudo.
