# Como projetar um alvo que serve para alguma coisa

O harness é a parte fácil e já está resolvida. O que decide se este laboratório
produz conhecimento ou ruído é o alvo — e especificamente a função `f`. Este
documento é o que aprendemos construindo os seis alvos atuais, incluindo os
erros que cometemos e que agora estão travados por teste.

A regra que resume tudo: **o loop pode rodar sem você; a definição de `f` não.**
Quando `f` está errado, o agente não trava — ele fica confiante.

---

## As nove propriedades de um alvo válido

Um alvo precisa das nove. Faltando qualquer uma, ele produz números que
parecem resultado e não são.

| # | propriedade | como se verifica |
|---|---|---|
| 1 | O gate tem mordida | `--selftest` verde, ≥ 5 mutantes rejeitados |
| 2 | O custo está dimensionado | `--budget` verde |
| 3 | O headroom é graduado | medido à mão; ver §3 |
| 3b | A medição não é trapaceável | candidato memoizador não pontua; ver §3b |
| 3c | O gate distingue o que o benchmark não distingue | propriedades compartilhadas por acidente; ver §3c |
| 3d | O headroom é total **e** distribuído | as duas coisas se opõem; ver §3d |
| 3e | A sonda de 100 s não denuncia teto subestimado | `sonda.py`; ver §3e |
| 3f | O poder foi medido **antes** de rodar | `piloto.py`; ver §3f |
| 3g | O espaço não é esgotável numa sessão — e foi **construído** assim | ver §3g |
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
razão de a barra de §3 reprovar dois dos seis alvos deste repositório.

O `sql_workload` foi a tentativa de escapar dessa tensão por outro caminho: em
vez de adicionar trabalho a um alvo, adicionar **artefatos** de custo comparável.
Funcionou (4,73× em 8 movimentos, o maior valendo 29%), e o preço foi quatro
rodadas de medição para equilibrar os oito. Ver §3g.

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

**O teste dos 100 segundos.**

```bash
python3 experiments/ablacao/sonda.py --alvo <nome>
```

Uma sessão única do modelo, sem estrutura nenhuma, com orçamento de 100 s; ela
mede o seed, roda, reavalia, e compara com o `lab.headroom_medido` declarado.
Custa ~US$ 0,50 e menos de três minutos. Fica fora do `make verify` e do CI de
propósito — gasta cota e leva minutos.

**O orçamento de 100 s não é livre de escala, e isso limita o que a sonda pode
dizer.** Ele foi escolhido quando uma avaliação custava dois ou três segundos. No
`sql_workload` uma avaliação custa 14 s: cem segundos não cobrem nem a leitura da
KB e dos nove artefatos, e a sonda mediu 0,98× — zero por cento do headroom, com
a sessão morta por tempo sem ter submetido nada. Isso **passa** em §3e (a
declaração de teto não está subestimada) e não é evidência de nada além de que a
sonda ficou curta. Uma fração baixa só significa "alvo difícil" quando o
orçamento comportava vários ciclos de medição; quando não comportava, ela
significa "sonda curta". Lendo a fração, olhe antes o custo de uma avaliação.

---

### ⚠ A fração é um teste de fumaça, não o critério. Descobri isso medindo.

A barra de "metade" acima foi escolhida por mim, sem evidência, a partir de um
único alvo. Rodada nos cinco alvos com o agente **enxergando** — depois de
consertar a falha 8, que impedia os agentes de medir — ela produziu isto:

| alvo | headroom declarado | ganho da sonda | fração |
|---|---|---|---|
| `sessionize` | 1,83× | 1,38× | 46% |
| `csv_normalize` | 6,20× | 3,76× | 53% |
| `sql_agg` | 4,25× | 3,76× | **85%** |
| `dedupe_match` | 3,55× | 3,77× | **109%** |
| `etl_agg` | 1,61× | 2,55× | **254%** |

**Três de cinco passam de 100%.** Uma fração acima de 100% não diz que o alvo é
fácil: diz que o **denominador está errado**. O `lab.headroom_medido` é medido à
mão, escrevendo versões progressivamente melhores e cronometrando — e a busca
supera a mão com folga. No `etl_agg`, por duas vezes e meia.

Então a fração mistura duas coisas que não se separam nela: quanto o alvo é
fácil, e quanto eu subestimei o teto dele. Como critério de aceitação, ela
reprova alvos por eu ter medido mal.

**O que a sonda serve para fazer, e é bastante:**

1. **Denunciar declaração subestimada.** Fração > 100% é prova de que o
   `headroom_medido` está errado, e isso é uma mentira no repositório que precisa
   ser corrigida. O `avo-lab verify` trata como erro bloqueante.
2. **Pegar o alvo que o agente resolve instantaneamente.** Uma sonda que chega
   perto do melhor conhecido, com o melhor conhecido sendo confiável, continua
   sendo o sinal barato que era.

**O que decide se um alvo discrimina é §3f, abaixo.** A pergunta não é "que
fração uma sessão pega", é "a diferença entre os braços que vão rodar é grande
comparada ao desvio entre sementes" — e isso não se responde por heurística. Se
responde medindo.

**O que isso não quer dizer.** Não quer dizer que o AVO não funciona. Quer dizer
que este alvo não o testa. O regime do paper são centenas de iterações num espaço
que nenhuma sessão esgota; um alvo cujo espaço uma sessão esgota em cem segundos
está fora desse regime por construção, e um resultado nulo nele é uma afirmação
sobre o alvo.

---

## 3f. O poder foi medido antes de o experimento rodar

A propriedade que faltava, e a que teria evitado os US$ 343 gastos em dois
experimentos cujos intervalos continham zero.

**O que aconteceu.** Nos dois, o desenho foi escolhido pelo orçamento — quatro
braços, quatro sementes, o que cabia — e o poder estatístico foi conferido
depois. Nos dois, a conferência disse que o n necessário era de 49 a 246
sementes por braço. Isso é uma coisa que se sabe **antes**, por menos de US$ 60.

**O que é um piloto de potência.** Não é o experimento: nenhuma hipótese é
testada, e nada que sai dele entra na análise. Ele mede duas coisas e as usa para
dimensionar:

```bash
python3 experiments/ablacao/piloto.py --alvo <nome>
```

- **o desvio entre sementes** do braço barato (5 sessões, ~US$ 8)
- **a trajetória por passo** de um run do braço caro (1 run), que dá a forma da
  curva, o custo por passo e se o supervisor chega a disparar

Com os dois, `n ≈ 2·(2,8·s/Δ)²` responde quantas sementes por braço detectam um
efeito do tamanho observado, a 5% e poder 80%.

**A barra.** Um alvo serve para comparar arquiteturas quando o n necessário para
distinguir os braços que vão rodar é **pagável**. Não há número universal aqui:
depende do custo por semente. No `sql_agg`, n=11 a US$ 21 por semente é US$ 250 e
o alvo serve; no `csv_normalize`, n=246 a US$ 12 seria US$ 3.000 por comparação e
não serve.

**Por que isto supera §3e.** A fração da sonda é uma proxy de um alvo; o piloto
mede **os braços que vão rodar de verdade**, com a variância que eles têm de
verdade. No `sql_agg` a sonda reprova (85%) e o piloto aprova (n=11 detecta os 5%
observados) — e o piloto é quem tem a informação, porque a diferença que importa
não é "sonda contra teto", é "`full` contra `greedy`".

**Declare no `target.yaml`**, como o headroom:

```yaml
lab:
  piloto_cv: 0.042          # desvio/média do braço barato, entre sementes
  piloto_n_para_5pct: 11    # sementes por braço para detectar 5%
  piloto_nota: >-
    5 sessões de greedy, 4,55x ± 0,193; um full de 8 passos, 4,78x, US$ 21,18
```

---

## 3g. Como se constrói um alvo que uma sessão não esgota

§3e diagnostica o problema e §3f decide se um alvo específico serve. Nenhuma das
duas diz **como construir** um alvo que sobreviva às duas. Esta seção é o que
aprendemos tentando: o `sql_workload` foi projetado de trás para frente a partir
desta pergunta, e os números abaixo são dele.

Dois mecanismos, e o segundo é o que importa.

### Mecanismo 1: Amdahl de propósito — e por que ele NÃO basta

> **Medido depois, e desmentido em parte.** O piloto do `sql_workload` mostrou que
> este mecanismo sozinho não cria a fricção que ele parece criar. O primeiro passo
> do `full` reescreveu **as oito consultas de uma vez** e saltou de 1,00× para
> 5,63×. "Uma mudança substancial por passo" é uma instrução ao agente, não uma
> restrição do alvo — e um agente com contexto suficiente atravessa a largura toda
> numa tacada. O que sustentou os sete passos seguintes foi o mecanismo 2. Leia
> esta seção sabendo disso: ela continua valendo para a DISTRIBUIÇÃO do headroom,
> que é o requisito de §3, e não para a não-esgotabilidade, que é o de §3e.

Em vez de um artefato para otimizar, **N artefatos de custo comparável no seed**.
No `sql_workload` são oito consultas SQL independentes mais o esquema físico que
elas compartilham. Consertar uma move o total em torno de 1/N; o ganho cheio
exige as N.

A distribuição do headroom, que §3 exige e que dois dos alvos anteriores não
alcançam, passa a ser consequência da construção em vez de sorte. Medido:

| alvo | headroom | movimentos | maior movimento |
|---|---|---|---|
| `etl_agg` | 1,61× | 2 | 98% |
| `sessionize` | 1,83× | 3 | 49% |
| `sql_agg` | 4,78× | 7 | não medido por movimento |
| **`sql_workload`** | **4,73×** | **8** | **29%** |

**A parte cara é o balanceamento, e ela não sai de graça.** A primeira versão do
`sql_workload` tinha uma consulta valendo 75% do ganho e outra valendo 1,4%.
Equilibrar exigiu quatro rodadas de medição e uma decisão de projeto que não é
óbvia: **cada relatório roda numa janela diferente** — trimestre, mês, semana —
escolhida para que os custos no seed fiquem na mesma ordem de grandeza. Isso é
defensável como domínio (um fechamento real não roda todos os relatórios no mesmo
período), mas foi a medição que escolheu os números, não o domínio.

### Mecanismo 2: movimentos que se destravam

Este é o que produz o regime do paper, e o mecanismo 1 sozinho não produz.

Oito movimentos independentes dão **largura**: uma sessão faz dois, um lineage
faz oito. Mas nada nisso exige *memória entre passos* — um agente com contexto
suficiente faria os oito de uma vez. O que exige memória é um movimento cujo
**valor muda de sinal** conforme o resto do candidato.

No `sql_workload` isso é literal. O **mesmo** `setup.sql`, aplicado a dois
candidatos diferentes:

| | consultas do seed | consultas reescritas |
|---|---:|---:|
| valor do índice + `ANALYZE` | **1,14×** | **2,10×** |
| valor do `ANALYZE` sozinho | **0,985×** (perda) | **1,375×** |

A mecânica é banal e é a razão de o alvo ser de SQL: um índice sobre uma coluna
que a consulta embrulha em função nunca é usado pelo planejador. O custo de
construir aparece imediatamente no regime frio; o benefício não aparece em lugar
nenhum até a consulta ser reescrita.

O efeito sobre a busca é o que interessa. Quem cria o índice primeiro mede 1,14×,
dentro do ruído acumulado de uma trajetória, e tem **todo motivo para descartar a
ideia**. Recuperá-la exige voltar a testar algo já medido como inútil, depois de
ter mudado outra coisa — que é exatamente a operação que um lineage com memória
entre passos permite e uma passada única não.

Há um segundo par no mesmo alvo, e ele é ainda mais nítido porque os dois lados
são perdas isoladas: reescrever `q5` em `UNION` mede 0,93× sem os índices
parciais de canal e país, e 1,06× com eles; criar os parciais mede 0,87× com a
`q5` antiga e 1,00× com a nova. **Nenhum dos dois paga sozinho.**

### A regra

> Largura sozinha mede contexto. O que mede *arquitetura de busca* é um espaço em
> que a ordem importa — onde existe pelo menos um movimento cujo valor medido
> muda de sinal conforme o que já foi feito.

O piloto confirmou a regra pelo lado que importa. Depois que o passo 1 varreu a
largura inteira, os sete passos seguintes foram todos de interação: o passo 2
tirou o `WHERE` parcial do índice e acrescentou uma coluna, o que **permitiu**
reescrever uma das consultas como leitura index-only — índice e consulta mudando
juntos, com o ganho aparecendo só na combinação. E o passo 6 **desfez** três
transformações que a referência escrita à mão considerava melhorias, depois de
medi-las em pares alternados. Nada disso cabe numa passada só.

E o corolário prático, que é o que dá trabalho: **você tem que medir as duas
ordens.** "O índice destrava depois da reescrita" é uma hipótese plausível e
estava certa aqui; a versão simétrica ("a reescrita destrava depois do índice")
também era plausível e estava errada. As duas custam a mesma meia hora de
medição, e sem elas o alvo tem uma propriedade que você acredita ter.

### O que o piloto mediu

O piloto de §3f rodou depois desta seção ser escrita, e é o primeiro dado da
bancada em que o `full` se separa do `greedy`:

| braço | resultado | custo |
|---|---|---|
| `greedy`, 5 sementes de 900 s | 5,620× ± 0,478 (cv 8,5%) | US$ 2,21 cada |
| `full`, 8 passos | **7,42×** (6,77× re-medido em pares) | US$ 22,61 |

O efeito é de **+32% não pareado, +20% a +29% pareado**, contra os 5% que a Fase
2A tentou detectar no `sql_agg` e não conseguiu. Com cv de 8,5%, um efeito de 20%
pede n=3 por braço e um de 15% pede n=5 — US$ 128 a US$ 228 por comparação.

Duas coisas apareceram de brinde, e nenhuma prova nada sozinha (n=1):

- O `full` teve dois passos rejeitados seguidos, o supervisor disparou, e o passo
  seguinte foi aceito e quebrou o platô. É a primeira vez que esta bancada vê o
  supervisor fazer o que o paper diz que ele faz.
- Os passos rejeitados custaram mais que os aceitos (US$ 4,63 e US$ 4,22 contra
  US$ 1,32–3,30). Um platô não é só ausência de ganho: é gasto.

Nada disso prova que a arquitetura do AVO funcione. Prova que **neste alvo a
pergunta tem uma resposta que o orçamento alcança** — o que nenhum dos cinco
alvos anteriores conseguiu oferecer.

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
[ ] a sonda de 100s roda e a fração NÃO passa de 100% (se passa, o headroom está subestimado)
[ ] piloto de potência rodado: `lab.piloto_cv` e `lab.piloto_n_para_5pct` declarados
[ ] o n necessário para distinguir os braços que vão rodar é PAGÁVEL
[ ] existe pelo menos um movimento cujo valor medido MUDA DE SINAL conforme o
    que já foi feito — e eu medi as DUAS ordens (§3g)
[ ] tentei trapacear no meu próprio alvo e não consegui
```

O último item não é retórica. Escreva um candidato que cacheia a saída entre
chamadas, um que detecta qual arquivo está lendo, um que memoriza o resultado.
Rode. Se algum pontuar, o alvo está quebrado, e é melhor descobrir agora do que
depois de quarenta versões construídas em cima. No `etl_agg` isso rendeu a §3b —
achada depois de o alvo já ter sido dado como pronto, com `--selftest` verde e
tudo.
