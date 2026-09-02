# Como projetar um alvo que serve para alguma coisa

O harness é a parte fácil e já está resolvida. O que decide se este laboratório
produz conhecimento ou ruído é o alvo — e especificamente a função `f`. Este
documento é o que aprendemos construindo os quatro alvos atuais, incluindo os
erros que cometemos e que agora estão travados por teste.

A regra que resume tudo: **o loop pode rodar sem você; a definição de `f` não.**
Quando `f` está errado, o agente não trava — ele fica confiante.

---

## As oito propriedades de um alvo válido

Um alvo precisa das oito. Faltando qualquer uma, ele produz números que
parecem resultado e não são.

| # | propriedade | como se verifica |
|---|---|---|
| 1 | O gate tem mordida | `--selftest` verde, ≥ 5 mutantes rejeitados |
| 2 | O custo está dimensionado | `--budget` verde |
| 3 | O headroom é graduado | medido à mão; ver §3 |
| 3b | A medição não é trapaceável | candidato memoizador não pontua; ver §3b |
| 3c | O gate distingue o que o benchmark não distingue | propriedades compartilhadas por acidente; ver §3c |
| 3d | O headroom é total **e** distribuído | as duas coisas se opõem; ver §3d |
| 3e | Uma sessão única **não** esgota o headroom | o teste dos 100 segundos; ver §3e |
| 4 | O score é diagnóstico | ≥ 2 regimes que são *formas* de dado diferentes |

Seis saíram de falhas reais desta bancada. Uma saiu do guia de targets do
upstream e é a mais barata de acertar.

Vale notar a ordem em que foram descobertas: 1 e 2 na primeira execução, 3 ao
corrigir 2, **3b depois de o alvo já ter sido declarado pronto**, e **3c só
quando alguém rodou a busca de verdade e tentou otimizar até o fim**, e **3e só
quando o alvo foi usado para aquilo que ele existia para fazer — comparar dois
braços — e não conseguiu**. Cada correção expôs a seguinte. É a razão de a checklist do fim deste documento
existir — e a razão de ela não estar terminada.

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
   `evalkit.no_disk_writes` instala um **gancho de auditoria**
   (`sys.addaudithook`) e recusa qualquer abertura para escrita. Duas sutilezas
   que valem manter: a violação é **anotada antes** de a exceção subir, então um
   candidato que embrulhe a operação em `try/except` não apaga o registro — só
   deixa de saber que falhou; e `.pyc`/`__pycache__` são liberados, porque um
   `import` tardio dentro da função medida grava bytecode e reprovar por isso
   seria reprovar candidato honesto.

   A primeira versão desta camada remendava `builtins.open`, `io.open` e
   `os.open`, e **uma auditoria adversarial a derrubou** com três candidatos de
   poucas linhas: `io.FileIO`, `os.popen` (que importa `subprocess` por dentro,
   invisível para qualquer checagem de AST) e `sqlite3.connect` (que abre o
   arquivo no C). Nenhum dos três passa por `builtins.open`. Num gancho de
   auditoria quem dispara o evento é o próprio interpretador, no ponto da
   abertura, então os três caem na mesma rede.

   Detalhe de implementação que é defesa, não estilo: `sys.addaudithook` não
   pode ser removido, então a guarda liga e desliga por um contador — e esse
   contador vive numa **célula de fecho**, não numa global do módulo. Numa
   global seria um interruptor com etiqueta, e uma linha do tipo
   `evalkit._PROFUNDIDADE = 0` desligaria a defesa inteira. Um ataque escrito
   exatamente assim passou numa auditoria antes da mudança.

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

**O que ainda não é coberto.** A camada 3 vê o que o interpretador reporta.
Código nativo carregado via `ctypes` que abra arquivo sem passar por evento de
auditoria continua invisível — e um candidato com alcance ao objeto da guarda
pode manipulá-lo, o que uma das auditorias demonstrou e resolveu no
`dedupe_match` tirando o objeto sensível de dentro do alcance em vez de tentar
limitar o alcance.

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

## 3c. O gate e o benchmark compartilham propriedades por acidente

Descoberto rodando a Sessão 2 do RUNBOOK contra o `etl_agg` — um alvo que já
tinha nove mutantes, dataset de gate separado, comparação contra soma verdadeira
com tolerância dimensionada, e três camadas anti-memoização.

**O ataque.** Um candidato que extrai os campos por posição relativa em vez de
por nome. Ele mede **+28,6%** sobre o melhor candidato honesto e passa no gate.

**Por que passa.** O `gate_adv` e os `perf_*` saem do mesmo gerador. Toda
propriedade que os dois compartilham — ordem dos campos, presença de todos os
campos, ausência de escapes, larguras, faixas de valor — é indistinguível de
contrato do ponto de vista do candidato. O gate só encontra o que ele foi
construído para **distinguir**, e este nunca tinha visto um registro com outra
ordem de campos.

**O que doeu.** Ao endurecer o gate (permutando a ordem das chaves em 1 de cada 3
registros), quatro das cinco versões do lineage daquele run passaram a reprovar
— incluindo versões que eu tinha commitado por achá-las honestas. Elas
dependiam da mesma suposição que eu havia rejeitado explicitamente numa outra
forma, e eu não percebi porque **o gate não me obrigou a perceber**.

O teto defensável real, com a extração dirigida reescrita sem as suposições,
ficou em +61,4% sobre o passe único — contra os +262% que o lineage inválido
mostrava. Cerca de 40% do ganho aparente era suposição.

**A regra.** Ao projetar um alvo, enumere explicitamente as propriedades que o
dataset de gate e o de benchmark compartilham **por acidente de geração**, e
decida uma a uma: ou vira contrato declarado na KB, ou o gerador do gate a
quebra em parte dos registros. Não deixe a terceira opção — "ninguém reparou" —
porque ela é a que a busca encontra.

Perguntas que descobrem essas propriedades depressa:

- Se eu embaralhar a ordem dos campos, o candidato ainda funciona?
- Se um campo faltar, ele falha alto ou dá resposta errada?
- Se um registro tiver o dobro do tamanho, ou um campo vazio, ou um escape?
- O que acontece se o campo que ele procura for o último do objeto?

**Otimização e trapaça não são categorias, são um gradiente.** Um candidato que
assume ordem de campos dá a resposta certa para qualquer arquivo com aquela
ordem: não é memorização nem detecção de dataset. A pergunta útil não é "isso é
trapaça?" e sim **"esta suposição está no contrato?"**. Se não está, ou entra no
contrato ou entra no gate.

---

## 3d. Espalhar e maximizar o headroom puxam em direções opostas

Descoberto construindo o quinto alvo (`sessionize`), e é a tensão que torna o
requisito de §3 mais difícil do que ele parece.

A primeira versão do `sessionize` mediu **4,18× em 3 movimentos**, com o maior
valendo 60% do ganho. Total bom, distribuição ruim. Para criar mais eixos,
enriqueci o contrato com dois agregados por sessão — páginas distintas e duração
somada. O resultado:

| versão do alvo | headroom total | maior fatia do ganho | movimentos |
|---|---|---|---|
| contrato simples (n, início, fim) | 4,18× | 60% | 3 |
| contrato enriquecido (+2 agregados) | **1,83×** | **49%** | 3 |

A distribuição melhorou e o total caiu pela metade. O motivo é direto: os
agregados novos são **trabalho irredutível por evento**. Eles entram igualmente
no seed e no candidato otimizado, então diluem a vitória do que era otimizável
(o parsing) sem criar ganho novo.

**A regra.** Adicionar trabalho a um alvo espalha o ganho e reduz o total. Para
aumentar as duas coisas ao mesmo tempo é preciso adicionar trabalho
**otimizável** — algo que o seed faz mal e um candidato pode fazer bem — e não
apenas mais contas. Isso é bem mais difícil de projetar do que parece, e é a
razão de a barra de §3 reprovar dois dos cinco alvos deste repositório.

Quando os dois não couberem, prefira o **total**: um alvo com 4× concentrado em
poucos movimentos ainda separa um braço que acha o movimento de um que não acha.
Um alvo com 1,8× bem distribuído não separa nada, porque 1,8× está perto demais
do ruído acumulado de uma trajetória inteira.

---

## 3e. O teto é alcançável numa sessão — e aí o alvo não separa arquiteturas

Descoberto rodando o controle honesto (`experiments/CONTROLE.md`): o `full` do
AVO contra uma sessão única do mesmo modelo, no `csv_normalize`, que tinha
passado em todas as propriedades anteriores.

**O que aconteceu.** Com 5,1× de headroom declarado, TODOS os braços pousaram na
mesma faixa:

| braço | relógio | US$ | ganho |
|---|---|---|---|
| sessão única morta aos 100 s | 108 s | 0,53 | 4,51× |
| sessão única, parada natural | 518 s | 2,60 | 4,23× |
| **`full`, 3 passos** | 2 454 s | 11,37 | **4,95×** |
| sessão única retomada até o orçamento | 2 186 s | 18,02 | 5,17× |

Uma sessão morta aos **cem segundos** chega a 4,51×. O AVO completo, com vinte e
três vezes mais relógio e vinte e uma vezes mais dinheiro, chega a 4,95×. Não há
diferença para medir porque não há espaço onde ela caiba: o teto do alvo está a
5,1× e todo mundo encosta nele.

**O número que fecha o caso.** Com o desvio observado, distinguir os braços
pediria de **121 a 4 250 sementes por braço** — de US$ 3.600 a mais de US$ 50.000
por comparação. Não é n insuficiente por avareza. É um alvo onde o efeito, se
existe, foi comprimido contra o teto até ficar menor do que qualquer orçamento
resolve.

**Por que as propriedades anteriores não pegam isso.** §3 exige headroom
graduado — 3× a 8× em ≥ 4 movimentos — e o `csv_normalize` tem: 5,1× em 6
movimentos, medidos à mão, conferidos pelo `verify`. O que §3 não pergunta é
**quanto desse headroom uma sessão única alcança sozinha**. Headroom graduado diz
que existem degraus; não diz que subi-los exige mais de uma sessão. Se um agente
sobe todos numa tacada, os degraus existem para o humano que os projetou e para
mais ninguém.

**A regra.** Um alvo serve para comparar arquiteturas de busca só se uma sessão
única alcançar uma **fração** do headroom. A parte que sobra é o espaço onde as
arquiteturas podem diferir; se não sobra nada, não há o que comparar.

**A fração certa é sobre o ganho disponível.** Um alvo de 5,1× tem 4,1× de ganho
para distribuir; uma sonda que mede 1,0× capturou zero por cento dele, não vinte.
Medida assim, a tabela acima fica muito mais dura:

| | ganho | fração do headroom disponível |
|---|---|---|
| sonda de 100 s | 4,51× | **86%** |
| AVO completo, 3 passos | 4,95× | 96% |
| sessão retomada até o orçamento | 5,17× | 102% |

Cem segundos pegam 86% de tudo que havia para pegar. Os 2 454 segundos e os
US$ 11,37 do `full` compram os 10% que sobraram. E a última linha passa de 100%
porque o headroom declarado (5,1×, medido à mão escrevendo versões melhores)
estava **subestimado** — a busca achou mais do que quem projetou o alvo achou.

**O teste dos 100 segundos.** Barato o suficiente para não ter desculpa:

```bash
python3 experiments/ablacao/sonda.py --alvo <nome>
```

Uma sessão única do modelo, sem estrutura nenhuma, com orçamento de 100s; ela
mede o seed, roda, reavalia, e compara com o `lab.headroom_medido` declarado.
Custa ~US$ 0,50 e menos de três minutos, e sai com código 1 se a fração passar de
metade.

Ela não entra no `make verify` nem no CI — gasta cota e leva minutos. É um passo
da checklist de alvo novo, feito uma vez, com o resultado anotado no
`target.yaml`.

Se a sonda pegar mais de metade do headroom, o alvo pode continuar servindo para
*otimizar* — ele mede melhora de verdade — mas não serve para *comparar
arquiteturas*, e a ablação montada em cima dele vai gastar milhares de dólares
para produzir intervalos que contêm zero.

**Medida nos cinco alvos deste repositório.** US$ 2,50 e vinte minutos ao todo:

| alvo | headroom | sonda 100 s | §3 | §3e |
|---|---|---|---|---|
| `sql_agg` | 4,25× | **49%** | passa | **passa** |
| `csv_normalize` | 6,2× | 68% | passa | reprova |
| `etl_agg` | 1,61× | 101% | reprova | reprova |
| `dedupe_match` | 3,55× | 111% | passa | reprova |
| `sessionize` | 1,83× | 9% | reprova | passa |

Duas leituras saem daí. A primeira: **um alvo de cada cinco serve**, e não era o
que estava sendo usado — a ablação e o controle rodaram no `csv_normalize`, que
reprova.

A segunda é estrutural e mais incômoda. Os alvos que sobrevivem à §3e são os de
headroom pequeno: o `sessionize` deixa 91% do espaço para a busca porque tem só
1,83× de espaço, e o `dedupe_match` é esgotado numa sessão porque os 3,55× dele
são fáceis. **Ser difícil por unidade de headroom e ter headroom são requisitos
que tendem a se opor** — é o mesmo tipo de tensão de §3d, e o `sql_agg` é o único
alvo aqui que tem os dois. Não por acaso é o que evolui SQL: otimizar uma
consulta exige medir trade-offs de índice entre regimes frio, quente e largo, e
isso não se resolve numa tacada como parsing de CSV se resolve.

**O que isso não quer dizer.** Não quer dizer que o AVO não funciona. Quer dizer
que este alvo não o testa. O regime do paper são centenas de iterações num espaço
que nenhuma sessão esgota; um alvo cujo espaço uma sessão esgota em cem segundos
está fora desse regime por construção, e um resultado nulo nele é uma afirmação
sobre o alvo.

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
[ ] headroom medido: >= 3x total, >= 4 movimentos, nenhum > 70% do ganho
[ ] `lab.headroom_medido` e `lab.movimentos` declarados no target.yaml
[ ] >= 2 regimes que são formas de dado diferentes
[ ] baseline real, não só o seed
[ ] a medição usa caminho novo E módulo novo por execução (anti-memoização)
[ ] enumerei o que o dataset de gate e o de benchmark compartilham por acidente
[ ] embaralhar a ordem dos campos / faltar um campo reprova quem depende disso
[ ] o teste dos 100 segundos: uma sessão única NÃO pega mais de metade do headroom
[ ] tentei trapacear no meu próprio alvo e não consegui
```

O último item não é retórica. Escreva um candidato que cacheia a saída entre
chamadas, um que detecta qual arquivo está lendo, um que memoriza o resultado.
Rode. Se algum pontuar, o alvo está quebrado, e é melhor descobrir agora do que
depois de quarenta versões construídas em cima. No `etl_agg` isso rendeu a §3b —
achada depois de o alvo já ter sido dado como pronto, com `--selftest` verde e
tudo.
