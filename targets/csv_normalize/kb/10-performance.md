# Onde o tempo vai, em normalização de texto

Números medidos neste laboratório, no seed, sobre `perf_sujo.csv` (9.000 linhas,
18 colunas, ~150 bytes por linha). São ordem de grandeza e não promessa: meça
você mesmo, e meça depois de cada mudança.

## O mapa de custo do seed

| fatia | % do tempo | comentário |
|---|---|---|
| resolver a `uf` | ~43% | dentro dela, tirar acento é ~32% do total |
| resolver a `data` | ~25% | dentro dela, `strptime` é ~18% do total |
| ler e montar as linhas (`DictReader`) | ~12% | 18 colunas viram 18 entradas de dict por linha |
| normalizar o `valor` | ~11% | gramática + regra do separador |
| normalizar o `nome` | ~10% | NFC, largura zero, colapso de espaço |

Três leituras disso, e elas importam mais que os números:

**O que domina não é o parsing do arquivo, é o que você faz com cada campo.** Ler
9.000 linhas de CSV custa uma fração do tempo; decidir o que cada string
significa custa o resto. Otimizar a leitura antes de olhar para os campos é
otimizar 12% e deixar 88% em pé.

**O caminho por caractere é o inimigo.** `tirar_acentos` sozinho chama
`unicodedata.combining` quase um milhão de vezes num arquivo de 9.000 linhas,
porque roda para cada caractere de cada nome de estado, para cada linha. Todo
laço em Python que visita caracteres é onde o tempo mora.

**Trabalho feito e jogado fora é trabalho.** O contrato só pede `nome`, `uf`,
`data` e `valor` da linha **vencedora** de cada chave. No regime `dup`, com 180
documentos para 9.000 linhas, 98% das linhas perdem a disputa. Normalizar o nome
delas é computar e descartar.

## Técnicas que valem a pena conhecer

**Tabela de consulta no lugar de varredura.** Resolver a UF percorrendo 27 pares
e recalculando a forma sem acento de cada nome a cada linha é O(27) chamadas de
função por linha. Um dicionário montado uma vez no import é O(1). Este é o maior
ganho isolado disponível, e é o mais banal: nada de esperto, só não repetir o
que não muda.

**Caminho rápido para ASCII.** `str.isascii()` é uma checagem de flag no objeto
string, praticamente de graça. Para uma string ASCII, `unicodedata.normalize`,
a remoção de largura zero e a remoção de acento são todas identidade. Testar
antes de chamar troca uma chamada de C por um teste booleano — e o regime
`limpo` é quase todo ASCII. Cuidado: isso é um atalho para o *caso comum*, não
uma suposição sobre o arquivo. O caminho geral tem que continuar existindo e
tem que continuar certo, porque o `sujo` e o gate passam por ele.

**Fatiar em vez de `strptime`.** `datetime.strptime` monta um regex, casa,
constrói um `datetime` e o descarta. Para três formatos de largura fixa,
`int(s[0:4])` e uma checagem de calendário fazem o mesmo trabalho sem nada
disso. Cuidado com a equivalência: `strptime` aceita `3/4/2024` e `%Y` exige
exatamente quatro dígitos — o contrato declara largura fixa justamente para que
as duas implementações concordem.

**Um único passe.** Materializar todas as linhas, depois todos os registros,
depois agrupar, e só então percorrer cada grupo mais duas vezes custa memória e
três travessias. Acumular direto num dict indexado pela chave, decidindo o
vencedor na hora, elimina as três.

**A forma do acumulador importa.** Um dict por grupo é legível; uma lista de
posições fixas evita o hash de string a cada atualização de campo. A diferença é
pequena por linha e real no agregado, e aparece mais no regime `dup`, onde há
poucas chaves e muitas atualizações por chave.

**`csv.reader` em vez de `csv.DictReader`.** O `reader` é o parser em C. O
`DictReader` é um invólucro em Python que constrói um dicionário de 18 entradas
por linha para você usar cinco. Ler o cabeçalho uma vez e guardar os cinco
índices dá o mesmo resultado sem o invólucro. Guardar os índices **lidos do
cabeçalho** é otimização; escrever os índices na mão é a suposição que o gate
existe para punir, porque a ordem das colunas muda entre arquivos.

**Ligação local de nomes.** Em laço quente, `converte = normalizar_valor` antes
do laço evita uma busca de global por linha. Vale o mesmo para métodos de dict:
`get = saida.get`.

**Sobre `re.compile` dentro do laço.** É menos caro do que parece: `re.compile`
consulta um cache interno do módulo `re`, então recompilar a mesma expressão é
uma busca em dicionário, não uma compilação. Tirar do laço vale poucos por
cento. O ganho de verdade é **não usar o regex**: `str.translate` para apagar um
conjunto fixo de caracteres e `" ".join(s.split())` para colapsar espaço fazem o
trabalho em C, sem o motor de expressões. Isto está escrito aqui porque a
intuição contrária é comum e custa uma iteração inteira de busca para ser
desmentida.

## O que não fazer

- **`linha.split(",")`.** É várias vezes mais rápido que o módulo `csv` e está
  errado. O gate tem campo citado com vírgula dentro, campo citado com quebra de
  linha dentro e aspas duplicadas. Isso não é uma pegadinha: é o motivo de o
  módulo `csv` existir.
- **Índices de coluna escritos na mão.** A ordem das colunas do arquivo de gate
  é diferente da dos arquivos de performance. Leia o cabeçalho.
- **Tabela de acentos montada à mão** no lugar da decomposição NFD. Funciona
  para os acentos que você viu e falha no primeiro que você não viu — e há um no
  gate.
- **Detectar a localidade da data pelo conteúdo** ("se o primeiro número for
  maior que 12, é dia"). O contrato declara dia-primeiro, sempre. Heurística
  aqui é aleatoriedade com passos extras.
- **Memorizar resultados, cachear entre execuções, indexar por caminho de
  arquivo.** O avaliador entrega um caminho diferente a cada execução e reprova
  qualquer execução mais rápida que ler o próprio arquivo de entrada. Um cache
  faz o número subir sem que nada tenha ficado mais rápido, e não é uma
  transformação que sobreviva a um dado novo.
- **Hardcodar chaves ou resultados deste dataset.** Passa no gate e não vale
  nada; o supervisor cobra.
