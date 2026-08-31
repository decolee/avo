# Contrato de `normalize` — a verdade sobre a saída

```python
normalize(path: str) -> dict[str, dict]
```

Um CSV de cadastro exportado de sistema legado entra; registros canônicos saem,
um por documento, já deduplicados. Este documento descreve o comportamento
exigido caractere a caractere. Onde a prosa e `eval.py` divergirem, `eval.py` é
a verdade — mas eles não devem divergir, e se divergirem isso é um bug do
laboratório e vale reportar.

## O arquivo de entrada

Dezoito colunas, das quais a transformação usa **cinco**: `doc`, `nome`, `uf`,
`data_ref`, `valor`. As outras treze existem porque existem no mundo.

Três fatos sobre o formato que não são negociáveis, porque o dataset que decide
correção os exercita de propósito:

- **A ordem das colunas muda entre arquivos.** O cabeçalho é a fonte da verdade.
  Decorar posições funciona no benchmark e reprova no gate.
- **Pode haver BOM** (`U+FEFF`) no começo. Abra com `encoding="utf-8-sig"`.
- **É CSV de verdade, não texto separado por vírgula.** Há campo citado com
  vírgula dentro, campo citado com quebra de linha dentro, aspas duplicadas
  (`""`) dentro de campo citado, e terminadores `\r\n` e `\n` misturados no
  mesmo arquivo. Use o módulo `csv` com `newline=""`.

## Chave

O documento canonizado:

1. descarte tudo que não for dígito ASCII (`0`-`9`);
2. sem nenhum dígito, ou com mais de 14, a **linha inteira é descartada** — ela
   não aparece na saída nem conta em lugar nenhum;
3. até 11 dígitos: preencha com zeros à esquerda até **11** (CPF);
4. de 12 a 14 dígitos: preencha com zeros à esquerda até **14** (CNPJ).

Então `123.456.789-09`, `12345678909` e `12345678909` sujo de espaço são a mesma
chave `"12345678909"`; `1234567` e `00001234567` são a mesma chave
`"00001234567"`. A **ordem** das chaves no dict devolvido não importa; o conjunto
sim.

## Valor

| campo | tipo | definição |
|---|---|---|
| `n` | int | linhas do arquivo que caíram nesta chave, **antes** da deduplicação |
| `nulos` | int | quantas dessas linhas tinham `valor` numa sentinela de nulo declarada |
| `invalidos` | int | quantas tinham `valor` não vazio, não sentinela e não numérico |
| `nome` | str | texto normalizado da linha **vencedora** |
| `uf` | str \| None | sigla de duas letras da linha vencedora, ou `None` |
| `data` | str \| None | data ISO da linha vencedora, ou `None` |
| `valor` | float \| None | número da linha vencedora, 2 casas, ou `None` |

`nulos` e `invalidos` contam **todas** as linhas do grupo, inclusive as
descartadas na deduplicação. `nome`, `uf`, `data` e `valor` vêm só da vencedora.
Essa assimetria é deliberada: contagem de qualidade de dado é sobre o lote,
valor canônico é sobre o registro que sobreviveu.

## Deduplicação e desempate

Entre as linhas que compartilham a chave:

1. vence a de **`data` maior**;
2. linha com `data is None` perde para qualquer linha com data;
3. no empate — mesma data, ou ambas sem data — vence a que aparece **por último**
   no arquivo.

A regra 3 existe porque um export legado costuma anexar a correção no fim. Ela é
declarada e não inferida: `dict[chave] = valor` puro implementa "último vence"
mas ignora a regra 1, e `setdefault` implementa "primeiro vence" e ignora as
duas. O gate rejeita as duas coisas.

## Texto (`nome`)

Nesta ordem:

1. `unicodedata.normalize("NFC", s)` — `e` + acento combinante vira `é`;
2. remova os caracteres de largura zero `U+200B`, `U+200C`, `U+200D`, `U+FEFF`;
3. colapse cada sequência de espaço em **um** espaço e descarte as pontas;
4. `.upper()`.

"Espaço" aqui é qualquer caractere para o qual `str.isspace()` é verdadeiro —
inclui `U+00A0` (não-quebrável), `U+2009` (fino), `U+3000` (ideográfico),
tabulação, e a quebra de linha que veio de dentro de um campo citado.
`" ".join(s.split())` faz o passo 3 inteiro de uma vez e acerta todos eles.

Os caracteres de largura zero **não** são espaço: `str.isspace()` é falso para
eles e `split()` não os enxerga. Ficam grudados no meio da palavra e destroem a
igualdade sem aparecer na tela. Por isso são removidos num passo próprio.

As sentinelas de nulo **não** valem para `nome`: `"N/A"` no campo nome vira o
texto `"N/A"`. O nome é o que o cadastro escreveu, e quem consome quer ver o
lixo. Um nome só de espaço vira a string vazia, não `None`.

## Unidade federativa (`uf`)

A coluna vem ora como sigla, ora como nome por extenso, em qualquer caixa e com
ou sem acento. A resolução:

1. normalize o texto pela regra acima (NFC, largura zero, espaço, caixa alta);
2. vazio ou sentinela de nulo → `None`;
3. descarte os diacríticos combinantes (decomponha em NFD e jogue fora tudo que
   tenha `unicodedata.combining(c) != 0`);
4. procure o resultado entre as 27 siglas e os 27 nomes das unidades federativas,
   também sem acento e em caixa alta;
5. achou → a sigla de duas letras; não achou → `None`.

Então `SP`, ` sp `, `São Paulo`, `SAO PAULO`, `Sa`+`U+0303`+`o Paulo` e
`Rio  de   Janeiro` resolvem; `XX` e `-` viram `None`.

O passo 3 é uma regra **geral**, não uma tabela dos acentos que este arquivo por
acaso contém. Trocar `SÃO PAULO` por `SAO PAULO` com um `str.translate` montado
à mão é rápido e funciona — até chegar `SÃO PAÜLO`, que a regra geral resolve
para `SP` e a tabela não. O gate tem essa linha.

## Data (`data`)

Exatamente três formatos de entrada, todos de **largura fixa** (com zero à
esquerda):

| entrada | exemplo | leitura |
|---|---|---|
| `AAAA-MM-DD` | `2024-04-03` | 3 de abril de 2024 |
| `DD/MM/AAAA` | `03/04/2024` | 3 de abril de 2024 — **dia primeiro** |
| `DD-MM-AA` | `05-06-60` | 5 de junho de **2060** |

Saída sempre `"AAAA-MM-DD"`.

**A ambiguidade e como ela foi resolvida.** `03/04/2024` é 3 de abril ou 4 de
março? A fonte é um sistema brasileiro, então a regra declarada é **dia
primeiro, sempre**. Isso tem consequência: `04/13/2024` — que um leitor
mês-primeiro leria como 13 de abril — tem mês 13, não existe, e vira `None`. Não
há detecção heurística de localidade; há uma regra e ela vale para todas as
linhas.

**Janela do ano de dois dígitos:** `00`-`68` → `20xx`, `69`-`99` → `19xx`. É a
janela POSIX, a mesma que `%y` do `strptime` da stdlib usa. `05-06-68` é 2068 e
`05-06-69` é 1969.

**Validade de calendário** é exigida, com ano bissexto de verdade: `29/02/2024`
resolve, `29/02/2023` e `31/02/2024` viram `None`.

Qualquer outra coisa — `05/06/24`, `2024-13-01`, `3/4/2024`, texto livre, e todas
as sentinelas de nulo — vira `None`. Não é erro; é ausência de data.

## Número (`valor`)

A gramática, de fora para dentro:

```
valor  := espaços? ( "(" espaços? corpo espaços? ")" | corpo ) espaços?
corpo  := (sinal | moeda)* numero          # no máximo um de cada, qualquer ordem
sinal  := "+" | "-"
moeda  := "R$" | "$"
numero := [0-9.,]+
```

Parênteses significam **negativo**: `(1.234,56)` é `-1234.56`. É a convenção
contábil, e ignorá-la troca o sinal de todo lançamento a crédito.

**A regra do separador decimal**, aplicada a `numero`:

| situação | o separador é | exemplo |
|---|---|---|
| aparecem `.` **e** `,` | o que ocorre por **último** é o decimal; o outro é milhar | `1.234,56` → 1234.56 · `1,234.56` → 1234.56 |
| aparece só um, **uma** vez, com **3** dígitos depois | milhar | `1.500` → 1500.0 · `1,500` → 1500.0 |
| aparece só um, **uma** vez, com outra quantidade | decimal | `1,5` → 1.5 · `1.23` → 1.23 |
| aparece só um, **mais de uma** vez | todas milhar | `1.234.567` → 1234567.0 |
| não aparece nenhum | inteiro | `1234` → 1234.0 |

Todos os separadores que não são o decimal são removidos; os grupos de milhar
**não** são validados. O número resultante é arredondado a **2 casas**:
`12,3456` vira `12.35`.

A regra dos três dígitos é heurística porque a fonte é genuinamente ambígua —
`1.500` pode ser mil e quinhentos ou um e meio, e o arquivo não diz qual. A
escolha aqui foi ser determinística, não adivinhar certo. Ela tem um efeito
colateral que o gate cobra: `0,005` vira `5.0`, porque tem três dígitos depois da
vírgula. Implemente a regra como está escrita; "consertar" o caso esquisito
reprova.

## Nulo, inválido e a diferença entre os dois

Depois de tirar os caracteres de largura zero e os espaços das pontas, o valor é
uma **sentinela de nulo** se for vazio ou, em caixa alta, um destes:

```
"" "NULL" "N/A" "NA" "NONE" "NIL" "-" "--"
```

O traço sozinho é sentinela; `-5` é um número. Um campo só com espaço
não-quebrável é sentinela, porque `strip()` remove `\xa0`.

Se não é sentinela e não casa a gramática, é **inválido**. Os dois casos dão
`valor = None`, e é exatamente por isso que existem dois contadores: sem
`nulos` e `invalidos` separados, tratar `"-"` como lixo seria indistinguível de
tratá-lo como nulo, e o gate não teria como ver a diferença. As mesmas
sentinelas valem para `data_ref` e `uf`.

## Como a correção é decidida

Num dataset separado e adversarial (`data/gate_adv.csv`), nunca nos dados de
performance. Ele tem setenta e poucas linhas e cada uma existe para punir uma
suposição específica.

Campo a campo:

- `n`, `nulos`, `invalidos` — igualdade exata. Não há tolerância razoável para
  uma contagem errada.
- `nome`, `uf`, `data` — igualdade exata de string. Quando divergem, a mensagem
  mostra os codepoints em `ascii()`, porque `JOSÉ` contra `JOSÉ` na tela é
  indistinguível e a diferença NFC/NFD é literalmente invisível.
- `valor` — tem que estar a menos de meio centavo do número verdadeiro (o valor
  lido, sem o arredondamento final) **e** ser de fato um valor de duas casas.
  `None` só casa com `None`: ausente e zero são fatos diferentes sobre o mundo.

## Restrições

- Somente a biblioteca padrão. Verificado estaticamente antes de executar.
- O dataset é congelado: `dataset.lock.json` guarda o SHA256 de cada arquivo.
- Não escreva nada em disco; `normalize` só lê.
- Não guarde estado entre chamadas. O avaliador chama a função várias vezes de
  propósito e entrega um caminho diferente a cada execução; um cache indexado
  pelo caminho erra, e uma execução mais rápida que ler o próprio arquivo é
  reprovada por implausibilidade.
