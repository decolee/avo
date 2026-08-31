# Record linkage: o domínio, e o que cada técnica custa

Nomes medidos neste laboratório, em bancos de ~2.300 registros. Servem de ordem
de grandeza, não de promessa — meça você mesmo.

## O formato do problema

`n` registros geram `n(n-1)/2` pares. Em 2.300 registros isso é **2,6 milhões**
de pares por banco, 7,9 milhões nos três. Qualquer comparação que custe mais que
alguns microssegundos por par não cabe no orçamento se você olhar todos eles.

Daí sai a tensão inteira do alvo: **você não compra qualidade sem antes comprar
tempo**. Um comparador melhor colocado dentro do laço exaustivo estoura o teto
antes de melhorar o F1. As duas decisões — quais pares olhar e como compará-los
— são o mesmo problema, e tratá-las separadamente é o erro clássico.

## Os cinco eixos

### 1. Normalização

Transformar a string antes de comparar. É o mais barato de todos porque custa
**O(n)**, não O(n²): normalize uma vez por registro, guarde, e compare o
resultado. Fazer isso dentro do laço de pares é refazer o mesmo trabalho `n`
vezes por registro — o seed faz exatamente isso.

O que costuma valer, em ordem de retorno: caixa única; remoção de acento
(`unicodedata.normalize("NFD", …)` e descartar as marcas combinantes); pontuação
virando espaço; ordenação dos tokens (resolve "Silva, João" contra "João
Silva"); descarte de partículas sem conteúdo (`de`, `da`, `dos`, e, para razão
social, `LTDA`, `LIMITADA`, `S/A`, `ME`, `EIRELI`).

Cada campo tem a sua: telefone vira dígitos (e os últimos oito dígitos são mais
estáveis que os onze, porque DDD e o nono dígito aparecem e somem); documento
vira dígitos; data precisa de um formato canônico, porque três formatações
brasileiras da **mesma** data estão presentes nos dados.

### 2. Bloqueio

Não olhar todos os pares. Você escolhe uma ou mais chaves de bloco e só compara
registros que compartilham alguma chave. É o que transforma 2,6 milhões de pares
em algumas dezenas de milhares.

Chaves plausíveis: um token do nome, o prefixo dos primeiros caracteres, um
código fonético, os dígitos do telefone, o e-mail, o documento. Bloqueio por
**união** de várias chaves recupera o que uma chave sozinha perde.

Duas coisas dão errado aqui, e nas duas direções:

- **Bloco gigante.** Um token comum (`silva`, `santos`, `comercial`) aparece em
  centenas de registros, e um bloco de 300 sozinho gera 45 mil pares. Blocos
  cujo tamanho passa de uma fração pequena de `n` custam mais do que trazem;
  descartar esses tokens é uma decisão de projeto, não uma gambiarra.
- **Bloco cego.** Um erro de digitação na chave joga a duplicata para fora de
  todos os blocos, e ela nunca mais volta. Nenhuma comparação, por melhor que
  seja, recupera um par que o bloqueio não propôs. **O bloqueio é o teto do
  recall.**

Bloquear também mexe na precisão, e para melhor: dois registros que só coincidem
por acaso raramente compartilham chave.

### 3. Similaridade aproximada

Quando as strings não batem exatamente, quanto elas se parecem. As famílias
usuais, com o custo relativo:

| técnica | custo | boa para |
|---|---|---|
| igualdade de conjunto de tokens | baratíssima | ordem trocada, token a mais |
| Jaccard / Dice sobre tokens ou n-gramas | barata | token faltando, sobrenome a menos |
| `difflib.SequenceMatcher.ratio` | cara (dezenas de µs) | erro de digitação |
| Levenshtein escrito à mão | mais cara ainda em Python puro | idem |
| Jaro-Winkler | média, favorece prefixo igual | nomes próprios |

A regra prática é escada: filtre com o barato, e só pague o caro no que
sobreviveu. Rodar `SequenceMatcher` em todo par bloqueado costuma ser o maior
item da conta de tempo.

Cuidado com o que a similaridade compra junto: aproximar nomes traz recall e
**leva precisão**, porque neste cadastro existem pessoas diferentes cujos nomes
estão a uma letra de distância. Similaridade sem corroboração normalmente piora
o F1 — não é um bug seu, é a forma do problema.

### 4. Combinação de campos

Um campo isolado quase nunca decide. Nome forte com data conflitante é um
homônimo; telefone igual com nome completamente diferente é um domicílio
compartilhado, não a mesma pessoa; documento igual é praticamente conclusivo,
mas o documento está presente em menos de um terço dos registros.

As duas formas de combinar:

- **Regra.** Uma lista de condições suficientes ("documento igual", "nome
  normalizado igual e telefone igual"). Legível, previsível, e cega para o caso
  que ninguém escreveu.
- **Escore.** Cada campo contribui com um peso, e um limiar decide. Cobre o
  contínuo entre os casos, e o limiar vira um botão que troca precisão por
  recall diretamente.

Nos dois casos, o interessante não é só a evidência a favor: **evidência
contra** é o que separa homônimo de duplicata. Dois campos presentes dos dois
lados e diferentes valem mais do que dez campos vazios. Cuidado com a assimetria
do vazio: campo ausente não é evidência contra, e tratá-lo como se fosse derruba
o recall sem devolver precisão.

Todo par adversarial deste dataset foi construído com ao menos um campo presente
dos dois lados que o separa. A informação está lá.

### 5. Fechamento transitivo

Se A é duplicata de B e B é duplicata de C, o gabarito também contém A–C — mesmo
que A e C, olhados de perto, não se pareçam. Propagar as ligações (union-find,
ou componentes conexas) recupera exatamente esses pares.

O risco é simétrico e conhecido: uma única ligação errada funde dois grupos e
todos os pares cruzados viram falsos positivos. O custo de um erro cresce com o
tamanho do grupo. Fechar sobre ligações de alta confiança e não sobre todas é a
diferença entre ganhar e perder com a técnica.

## O que não fazer

- Ler o gabarito, ou qualquer arquivo. É verificado durante a execução.
- Guardar resultado em disco entre avaliações. Também é verificado.
- Depender da ordem dos registros. O gate permuta a entrada e compara.
- Afinar limiar no terceiro decimal para estes três bancos. Passa no gate, não
  vale nada, e a KB avisou.
- Codificar suposições sobre o formato exato destes dados — que o nome sempre
  tem três tokens, que o telefone sempre tem onze dígitos. Os três bancos têm
  formas diferentes de propósito, e o que vale é linkage geral.
