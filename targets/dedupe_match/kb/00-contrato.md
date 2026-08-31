# Contrato de `match` — a verdade sobre a saída e sobre o que reprova

```python
match(records: list[dict]) -> Iterable[tuple[str, str]]
```

## Entrada

Uma lista de registros de cadastro. Todos os campos são `str`; campo ausente
chega como `""`, nunca como `None`.

| campo | o que é | como costuma vir sujo |
|---|---|---|
| `id` | identificador do registro | limpo, único, e **opaco**: não codifica nada |
| `nome` | nome da pessoa ou razão social | caixa, acento, ordem de tokens, abreviação, erro de digitação |
| `cidade` | município | com e sem acento; às vezes vazio |
| `uf` | sigla do estado | às vezes vazia |
| `telefone` | um telefone | seis formatações diferentes para os mesmos dígitos |
| `email` | um e-mail | mesmo local, domínio trocado; some em parte das variações |
| `documento` | CPF ou CNPJ | pontuado ou só dígitos; **presente em menos de 40% dos registros** |
| `nascimento` | data de nascimento ou de fundação | `aaaa-mm-dd`, `dd/mm/aaaa`, `dd.mm.aaaa` |
| `endereco` | logradouro, número, complemento | `Rua`/`R.`, `Avenida`/`Av.`, complemento some |

O `id` é atribuído **depois** de embaralhar os registros. Ele não carrega
prefixo de entidade, e proximidade de `id` não significa nada. Não há atalho ali.

## Saída

Um iterável de pares `(id_a, id_b)` — lista, conjunto, gerador, tanto faz. Cada
par diz "estes dois registros são a mesma entidade do mundo real".

- A ordem **dentro** do par não importa: `(a, b)` e `(b, a)` são o mesmo par.
- A ordem **entre** os pares não importa.
- Cada par pode aparecer **uma vez só**.
- Os dois lados têm que ser diferentes, e os dois têm que existir na entrada.

Duplicata é uma relação transitiva sobre entidades: se um cadastro tem três
grafias da mesma pessoa, o gabarito contém os **três** pares, não dois.

## O que `correct` significa aqui — leia duas vezes

Este é um alvo de **qualidade**. Nos outros alvos da bancada, `correct` quer
dizer "a saída está certa". Aqui isso seria absurdo: se o gate exigisse acerto,
ele seria a própria métrica e não sobraria nada para maximizar.

Então **errar é legítimo e vale F1 baixo**. O que vale zero é violar o contrato.
São quatro cláusulas, todas verificadas num banco pequeno e deformado que existe
só para isso (`data/gate_bank.json`) — nunca nos bancos pontuados:

**Forma.** Iterável de pares de ids existentes. Sem id inventado, sem par
repetido, sem par de um registro consigo mesmo, sem devolver ids soltos.

**Orçamento.** O tempo de **todas** as chamadas de `match` soma num único teto.
Estourar vale zero, não "um pouco menos".

**Determinismo.** Duas chamadas com a mesma entrada devolvem o mesmo conjunto —
se usar sorteio, use semente fixa. E **permutar a ordem dos registros também não
pode mudar nada**: quem é duplicata de quem não depende de qual linha veio
primeiro. Essa segunda metade é mais rígida do que parece e rejeita
agrupamento guloso que percorre a lista na ordem em que ela chegou.

**Pureza.** `match` não lê arquivo e não escreve arquivo. Isso não é etiqueta:
enquanto o seu código tem o controle — **incluindo o corpo do módulo, no
import** — um gancho de auditoria do interpretador está ligado, e qualquer
leitura dentro do diretório do alvo, qualquer escrita em disco e qualquer evento
que saia do processo reprovam, inclusive se você engolir a exceção. Não existe
porta de trás por outra API: quem dispara o gancho é o CPython, no ponto em que
o arquivo é de fato aberto, e não o `open` do Python. `subprocess`,
`multiprocessing`, `ctypes`, `mmap` e `socket` também são negados
estaticamente, para você receber a recusa antes de rodar em vez de no meio.

Vale dizer por que a pureza está no gate e não numa recomendação: o gabarito
existe em disco, em `data/labels_*.json`. Um candidato que o abrisse marcaria
F1 = 1,0 sem ter resolvido nada, e nenhuma checagem de forma pegaria — a saída
estaria perfeita. Proibição de escrita é a mesma ideia uma camada acima: um
cache em disco atravessa avaliações e devolve trabalho já pago de graça,
comprando orçamento sem ter ficado melhor.

## Restrições

- Somente a biblioteca padrão. Verificado estaticamente antes de executar.
- O dataset é congelado: `dataset.lock.json` guarda o SHA256 de cada arquivo.
- Não mute a lista recebida esperando que isso sobreviva; você recebe uma cópia.
