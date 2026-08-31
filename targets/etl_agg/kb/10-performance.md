# Onde o tempo vai, em Python

Números medidos neste laboratório, num registro de ~345 bytes com dezesseis
campos. Servem de ordem de grandeza, não de promessa — meça você mesmo.

## O mapa de custo

Numa agregação JSONL ingênua, o tempo se divide grosso modo assim:

| fatia | custo relativo | comentário |
|---|---|---|
| `json.loads` por linha | dominante | materializa os dezesseis campos, você usa cinco |
| materializar listas por grupo | alto | uma lista por grupo, mais um objeto por linha viva até o fim |
| percorrer cada grupo N vezes | alto | uma passada por campo agregado é N passadas |
| aritmética da acumulação | baixo | somar float é barato perto do resto |

Duas consequências práticas: o que você faz **por linha** domina tudo, e o que
você deixa de fazer por linha vale mais que qualquer micro-otimização depois.

## Técnicas que valem a pena conhecer

**Um único passe.** Reagrupar depois de materializar custa memória e uma
travessia extra por campo. Acumular direto num dict indexado pela chave elimina
as duas coisas.

**A forma do acumulador importa.** Um dict por grupo é legível; uma lista de
posições fixas evita hashing de string a cada campo. A diferença é pequena mas
é real, e aparece mais no regime `narrow`, onde há poucos grupos e muitas
atualizações por grupo.

**Ligação local de nomes.** Em laço quente, `loads = json.loads` antes do laço
evita duas buscas de atributo por linha. Vale o mesmo para métodos de dict.

**Parsing dirigido.** `json.loads` constrói o registro inteiro. Se você precisa
de cinco campos de dezesseis, está pagando por onze. Extrair só o que interessa
é uma otimização legítima e de peso — mas é onde mora o risco: um extrator que
assume ordem fixa de campos, ausência de escapes ou largura fixa está codificando
propriedades **deste arquivo**, não do formato. O gate roda num dataset
diferente do benchmark justamente para achar esse tipo de suposição.

**`dict.get` vs `setdefault` vs `try/except`.** As três resolvem "primeira vez
que vejo esta chave". Custam diferente, e qual ganha depende de quantas chaves
novas aparecem — ou seja, muda entre `wide` e `narrow`.

## O que não fazer

- Arredondar durante a acumulação para "economizar". Muda o resultado; o gate
  pega. Veja `00-contrato.md`.
- Reduzir precisão (float32, inteiros de centavos com truncamento). Os notionais
  do dataset de gate estão na faixa onde isso aparece.
- Memorizar resultados, hardcodar chaves, ou cachear entre execuções. O
  avaliador chama a função várias vezes de propósito; um cache faz o número
  subir sem que nada tenha ficado mais rápido, e não é uma transformação que
  sobreviva a um dado novo.
