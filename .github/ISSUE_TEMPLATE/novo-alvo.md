---
name: Proposta de alvo novo
about: Propor um dominio novo para a bancada, antes de escrever codigo
title: "alvo: <nome>"
labels: ["alvo"]
---

Leia `docs/TARGET_DESIGN.md` antes. As perguntas abaixo sao as que costumam
matar uma proposta — melhor descobrir aqui do que depois de escrever o gerador.

**Dominio e tier:**
<!-- ex.: parsing de log, Tier 0 Python -->

**A funcao `f`, concreta:** o que e maximizado, e como e medido?
<!-- Sem candidato incumbente mais um numero para maximizar, o loop nao fecha.
     "Codigo mais legivel" e "arquitetura melhor" nao sao f. -->

**Como a correcao e decidida?** Qual dataset julga, e por que ele e capaz de
expor o erro que voce espera que apareca?

**Quais sao os >= 5 mutantes?** Liste os atalhos plausiveis que o gate tera que
rejeitar.

**Headroom estimado, e distribuido em quantos movimentos?**
<!-- Meta: 3x-8x em >= 4 movimentos independentes, nenhum valendo > 70%.
     Se voce so consegue imaginar UM movimento grande, o alvo nao serve para
     ablacao — que e o motivo de a bancada existir. -->

**Custo de UMA avaliacao do seed** (estimado, entre ~3s e 25s):

**O que este alvo mede que os quatro atuais nao medem?**
