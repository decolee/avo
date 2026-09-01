# Working notes

Scratch space that survives across variation steps. The framework never writes
here — it is yours.

Worth keeping: what you tried and what it measured, dead ends (so a later step
does not re-walk them), and any structure of the problem you had to work out.


## Beco sem saída — processamento em bytes (medido, não inferido)

**Hipótese.** Ler em modo binário evitaria 25.000 decodificações UTF-8 por
execução, decodificando só as ~8.500 chaves de grupo no final.

**Primeira medição: +6,90%.** Parecia bom. Mas o regime `wide` veio com ±18,2%
de coeficiente de variação, e a KB (`kb/20-medicao.md`) diz para desconfiar
disso. Medi de novo, três vezes, e depois comparei as duas versões lado a lado
fora do run dir:

| versão | geomean (3 medições) |
|---|---|
| v3 (str) | 14,67 / 14,13 / 14,53 |
| v4 (bytes) | 14,48 / 14,04 / 13,68 |

**A versão em bytes é ligeiramente PIOR.** O +6,90% era ruído.

**Por que não funciona.** A decodificação UTF-8 do CPython tem caminho rápido
para ASCII e roda em C — ela já era barata. Em troca, a versão em bytes paga:
`float()`/`int()` sobre `bytes` não é mais rápido que sobre `str`, a concatenação
da chave cria um `bytes` novo por linha do mesmo jeito, e o `.decode()` por grupo
no final é custo que a versão em `str` não tem.

**Não re-tentar.** Nem em variantes (`memoryview`, `os.read` em bloco): o gargalo
não é a decodificação.

**O que isto ensina sobre o alvo.** Depois do v3, o custo por linha já é quase
todo `find` + fatiamento + aritmética. Ganhos vão ter que vir de fazer menos
trabalho por linha, não de fazer o mesmo trabalho mais barato.

## Direção medida e REJEITADA — regex única assumindo ordem de campos

**O número.** Uma regex compilada encadeando os cinco campos com `.*?` mede
**+28,6%** sobre a v4 (5 rodadas intercaladas, amplitude 5,5%). É o maior ganho
isolado disponível neste ponto da curva, e está muito acima do ruído.

**Por que não commitei.** Ela só é rápida porque assume que os cinco campos
aparecem numa ordem relativa fixa dentro do registro. Testei três formas de
obter o ganho sem essa suposição, e nenhuma funciona:

| variante | vs v4 | supõe ordem? |
|---|---|---|
| regex única com `.*?` | **+28,6%** | **sim** |
| `finditer` sobre o arquivo inteiro | +7,6% | sim |
| cinco regexes independentes | −22,6% | não |
| alternação de nomes, uma varredura por linha | −46,2% | não |

A conclusão é que o ganho **é** a suposição, não um efeito colateral dela.

`kb/10-performance.md` nomeia exatamente isto como o risco do parsing dirigido:
"um extrator que assume ordem fixa de campos [...] está codificando propriedades
deste arquivo, não do formato". A ordem dos campos não está em
`kb/00-contrato.md`.

**O achado que importa: o gate não vê a diferença.** `gate_adv.jsonl` e os
`perf_*.jsonl` saem do mesmo gerador, com a mesma ordem de campos. Um candidato
que assume ordem passa no gate com folga. O gate existe para achar suposições
sobre a forma do dado e esta ele não acha.

Isso não é um problema deste candidato, é um buraco no alvo. Não dá para
consertar no meio do run — mexer no `gate_adv` muda `f` e invalida a comparação
entre as versões já commitadas. Fica registrado para a Sessão 2 (teste de
trapaça), cujo trabalho é exatamente esse.

**Para um run futuro, depois do gate endurecido:** se `gate_adv` passar a ter
registros com a ordem dos campos permutada, esta variante reprova e a questão
se resolve por medição em vez de por julgamento. Se mesmo assim alguém decidir
que ordem de campo é contrato, então declare no `kb/00-contrato.md` e o ganho
passa a ser legítimo.

## Platô declarado após a v5

Três otimizações mecânicas testadas, todas dentro do ruído:

| variante | vs v5 |
|---|---|
| constantes içadas de global para local | +0,2% |
| `buffering=1<<20` na leitura | −2,5% |
| as duas juntas | +0,5% |

A içada de globais render +0,2% diz onde o tempo está: `str.find` é dominado
pela varredura em si, não pela busca do nome. O buffer maior não ajuda porque o
arquivo já vem do cache de página.

**O que sobrou por linha depois da v5:** cinco `find`, três fatiamentos, duas
conversões numéricas, uma concatenação de chave, um acesso a dicionário e quatro
atualizações de lista. Nenhuma dessas é removível sem assumir algo sobre a forma
do registro — e a única suposição que renderia (ordem dos campos, +28,6%) está
registrada acima como rejeitada.

**Leitura da curva.** O alvo tem duas fases claras. Até a v3 os ganhos vêm de
parar de fazer trabalho desnecessário (materializar grupos, materializar o
registro inteiro, chamar função por campo) e são grandes: +52%, +76%, +17%. Da
v4 em diante sobra só micro-otimização, e ela some no ruído da máquina (±3%).

Isso é o platô, não falta de ideias: as ideias existem e foram medidas. O que
falta é headroom defensável.
