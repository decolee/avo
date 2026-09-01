# Working notes

Scratch space that survives across variation steps. The framework never writes
here — it is yours.

Worth keeping: what you tried and what it measured, dead ends (so a later step
does not re-walk them), and any structure of the problem you had to work out.


## Três direções medidas depois da v2 — todas rejeitadas, e por motivos diferentes

A v2 fecha em F1 0,757 (pessoas 0,861 · empresas 0,654 · ruidoso 0,771). A
fraqueza óbvia é a precisão em empresas: 0,52 com recall 0,89, ou seja, o dobro
de pares que deveria.

**(a) Mais evidência quando não há nascimento** — endereço com sobreposição, ou
nome com 3+ tokens distintivos. Resultado: **+0,46%**, empate. A precisão em
empresas foi de 0,516 para 0,522. A hipótese estava errada: o excesso de pares
não vinha do caminho do nome.

**(b) Rebaixar telefone e email de identificadores fortes** (exigindo também
sobreposição de nome). Resultado: **−8,2%**, rejeitado.

| banco | F1 v2 | F1 com (b) |
|---|---|---|
| empresas | 0,654 | **0,702** |
| pessoas | 0,861 | 0,754 |
| ruidoso | 0,771 | 0,636 |

Empresas melhorou de verdade — precisão 0,52 → 0,66. Pessoas e ruidoso
desabaram em recall. **Os três bancos querem regras diferentes, e a média
geométrica não deixa otimizar um às custas dos outros.** É exatamente o que ela
existe para fazer: uma regra que só serve para um tipo de entidade não é uma
melhoria do deduplicador, é um ajuste a um banco.

**(c) Meio-termo — telefone e email fortes, mas sujeitos ao veto por documento
ou nascimento divergente.** Resultado: **−4,9%**, rejeitado.

Este é o mais instrutivo dos três. O veto parece obviamente certo: se dois
registros têm nascimento preenchido e diferente, não são a mesma pessoa. Mas
num cadastro sujo — que é o problema — **nascimento divergente é muitas vezes
erro de digitação dentro da mesma entidade**, e é precisamente o caso que a
deduplicação existe para achar. Aplicar o veto a pares que já compartilham
telefone ou email joga fora justamente as duplicatas mais difíceis.

O veto continua valendo no caminho do NOME (onde está desde a v2), porque ali a
única evidência é a semelhança textual e o conflito realmente pesa mais.

**Onde estagnou.** A v2 é o melhor ponto encontrado. O caminho que sobra não é
mais ajuste de limiar: é reconhecer que pessoa física e pessoa jurídica são dois
problemas com regras distintas, e resolver isso sem olhar para qual banco está
rodando — o que exigiria inferir o tipo de entidade dos próprios campos.
