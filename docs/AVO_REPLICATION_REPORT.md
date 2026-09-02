# AVO_REPLICATION_REPORT.md — v0.1

> **Nota de estado (v0.3) — o que este repositório fez com este relatório.**
>
> O relatório abaixo continua sendo a base de evidência e não foi reescrito: as
> classificações CONFIRMADO / INFERIDO / ESPECULATIVO / REPRODUCTION-SPECIFIC
> valem como estão. Três atualizações:
>
> 1. **A auditoria foi refeita e confere.** `gatordevin/avo` no commit
>    `f6dad9e639d3c9e5d5ac9ccacbe076d82cfa39d2` (fixado em `vendor/avo.lock`):
>    48 testes passam. O `resolve_target` procura em `Path.cwd()/targets` antes
>    dos alvos internos, o que significa que nossos alvos são encontrados sem
>    copiar nada para dentro do `vendor/` — a cópia que o bootstrap antigo fazia
>    era desnecessária e destrutiva.
> 2. **A recomendação da §7 ("não construa o OpenAVO Lab") foi seguida, e vale
>    reafirmá-la com precisão:** não construímos harness. O que este repositório
>    constrói são **alvos, gate e disciplina de verificação** — a parte que o
>    upstream deliberadamente deixa para o domínio. Ver `docs/TARGET_DESIGN.md`.
> 3. **O Estágio 1 da §7 (a ablação) ganhou pré-registro** em
>    `docs/ABLATION_PROTOCOL.md`, escrito antes de rodar, com métrica primária,
>    n, método de análise e efeito mínimo detectável fixados. A §6 deste
>    relatório argumenta que essa ablação é a contribuição real disponível; o
>    protocolo é a tentativa de fazê-la de forma que o resultado signifique algo.
>
> Uma coisa que a §6 não previu: o risco maior não era o experimento estar
> errado, era o **alvo** estar errado. Quatro modos de falha de alvo foram
> encontrados na prática, e três deles produziriam números que pareceriam
> resultado. Estão catalogados em `docs/TARGET_DESIGN.md`.

**Escopo desta versão:** Fase 1 (Source Discovery), Fase 2 parcial (decomposição via abstract + mapa paper→código), Fase 11 (auditoria da reprodução aberta, executada de fato), Fase 12 (gap analysis) e revisão crítica do plano.
**Data:** 26/08/2026
**Status honesto:** as 20 fases do master prompt não foram executadas. O que segue é a base de evidência necessária antes de qualquer arquitetura. Ver §9 para o que NÃO foi verificado.

---

## 0. Nota sobre o ambiente

O master prompt foi escrito para o Claude Code (criar `research/`, `architecture/`, subagentes paralelos, clonar repos). Estamos na interface de chat. Consegui mesmo assim: buscar a web, ler as fontes primárias, **clonar o repositório de reprodução, inspecionar o código e rodar a suíte de testes**. O que não consego aqui é persistir a árvore de arquivos — este relatório é o artefato único. Levar para o Claude Code depois é trivial.

---

## 1. SOURCE MAP — verificação de existência

Antes de qualquer coisa: **tudo que você citou existe.** Isso não era garantido e era o risco nº1 do projeto.

| Fonte | Status | Detalhe verificado |
|---|---|---|
| arXiv:2603.24517 | ✅ **CONFIRMADO** | <cite index="27-1">"AVO: Agentic Variation Operators for Autonomous Evolutionary Search", submetido em 25/03/2026, cs.LG, 23 autores: Terry Chen, Zhifan Ye, Bing Xu, Zihao Ye, Timmy Liu, Ali Hassani, Tianqi Chen, Andrew Kerr, Haicheng Wu, Yang Xu, Yu-Jung Chen, Hanfeng Chen, Aditya Kane, Ronny Krashinsky, Ming-Yu Liu, Vinod Grover, Luis Ceze, Roger Bringmann, John Tran, Wei Liu, Fung Xie, Michael Lightstone, Humphrey Shi</cite> |
| Blog NVIDIA ago/2026 | ✅ **CONFIRMADO** | developer.nvidia.com, publicado 21/08/2026 13:00 UTC, modificado 21/08 21:08 UTC. Autores: Terry Chen, Yeyin (Eva) Zhu, Zhifan Ye, Jean-Francois Puget, Humphrey Shi |
| `gatordevin/avo` | ✅ **CONFIRMADO** | Clonado. Devin Willis, último commit 21/08/2026. 42 arquivos .py, 7.330 LOC, 38 .md, 48 testes |
| `SilentMathematician/avo` | ⚠️ **APARECE EM BUSCA, NÃO CLONÁVEL** | Descrito como "implementation of arXiv 2603.24517" como extensão do coding agent `pi`. Clone falhou (privado ou removido). Não auditável |
| VISTA | ✅ **CONFIRMADO** | vista-research.github.io — "A Visual Harness For Reasoning in an Interactive World" |
| Tycho | ✅ **CONFIRMADO** | arXiv:2607.28287, "Active Abstraction with Programmatic World Models for ARC-AGI-3", github.com/NIMI-research/Tycho |
| FlashAttention-4 | ✅ **CONFIRMADO** | arXiv:2603.05451 (Zadouri, Hoehnerbach, Shah, Liu, Thakkar, Dao) |
| Repositório oficial NVIDIA do AVO | ❌ **NÃO ENCONTRADO** | Nenhum código-fonte oficial localizado. O blog só linka paper, ARC Prize, VISTA e Tycho |

**Correção ao seu prompt:** você atribuiu a reprodução a `gatordevin/avo` — correto. A busca também retorna `SilentMathematician/avo`, que **não é clonável**. Trate a segunda como inexistente até prova em contrário.

---

## 2. EVIDENCE LEDGER

### CONFIRMADO (declarado por NVIDIA/autores)

| # | Claim | Fonte | Implicação para replicação |
|---|---|---|---|
| C1 | AVO substitui mutação/crossover/heurísticas fixas por **coding agents autônomos**; o agente é o operador de variação, não um gerador de candidatos | <cite index="25-1">abstract arXiv</cite> | É a tese central. Reproduzível conceitualmente |
| C2 | O agente consulta **lineage atual, knowledge base de domínio e feedback de execução** para propor, reparar, criticar e verificar edições | <cite index="25-1">abstract arXiv</cite> | Define os 3 inputs mínimos: `P_t`, `K`, `f` |
| C3 | 7 dias contínuos em MHA em B200; supera cuDNN em até **3,5%** e FlashAttention-4 em até **10,5%** | <cite index="25-1">abstract arXiv</cite> | Não reproduzível sem B200 |
| C4 | Transfere para grouped-query attention com **~30 min** de adaptação autônoma adicional | <cite index="25-1">abstract</cite> | Evidência de generalidade intra-domínio |
| C5 | **500+ direções exploradas, 40 versões de kernel commitadas** em 7 dias | <cite index="43-1">blog NVIDIA</cite> | Taxa de aceitação ≈ 8%. Métrica-alvo para nossa réplica |
| C6 | Dois mecanismos são "particularmente importantes": **memória persistente e supervisão** | <cite index="43-1">blog NVIDIA</cite> | Prioridade de implementação |
| C7 | Memória persistente carrega **implementações anteriores, resultados de avaliação, saídas de compilador e profiler, e raciocínio acumulado** | <cite index="43-1">blog</cite> | Lista explícita do que sobrevive ao contexto |
| C8 | Supervisor monitora a trajetória para **estagnação ou ciclos improdutivos repetidos** e redireciona; o agente principal mantém a decisão sobre o que inspecionar/mudar/testar | <cite index="43-1">blog</cite> | Supervisor **não** assume o controle — só redireciona |
| C9 | ARC-AGI-3: **100,00 RHAE, 183 níveis, 25 ambientes, 6.624 ações**, com Claude Opus 5 | <cite index="43-1">blog</cite> | Público apenas |
| C10 | VISTA: **7.542 ações** para os mesmos 183 níveis → AVO ~12% menos | <cite index="43-1">blog</cite> | Comparação cross-system, não ablação |
| C11 | **Modalidade texto puro**: cada observação é um grid textual exato **64×64**, sem imagens nem image tokens enviados ao modelo. VISTA usa PNG 512×512 como configuração primária | <cite index="43-1">blog</cite> | Diferença de interface crítica e reproduzível |
| C12 | O agente recebe as ações disponíveis **sem descrição das regras ou objetivos** e infere efeitos por interação | <cite index="43-1">blog</cite> | Define o contrato do ambiente |
| C13 | Adotaram os princípios de **interação direta do VISTA** e reimplementaram a interface independentemente; recusaram o world-model programático do Tycho para não introduzir camada ARC-específica | <cite index="43-1">blog</cite> | Decisão de design deliberada em favor da generalidade |
| C14 | **"O agente subjacente permanece o mesmo; apenas as ferramentas específicas do ambiente e a avaliação mudam"** | <cite index="43-1">blog</cite> | É a definição operacional do Nível 3 de sucesso |
| C15 | Testes adicionais com **GPT-5.6 Sol** num subconjunto: Sol atingiu níveis equivalentes mais rápido em wall-clock em vários casos; Opus usou menos ações ambientais em comparações de nível equivalente | <cite index="43-1">blog</cite> | Suporta o design model-agnostic (Fase 15) |
| C16 | NVIDIA declara explicitamente: **não é ablação controlada**; os sistemas diferem em backend, representação de observação, memória e gestão de contexto; **"este experimento não isola a contribuição individual [da memória]"** | <cite index="43-1">blog</cite> | **É a maior oportunidade do nosso projeto** |
| C17 | Resultados cobrem apenas o **public set**; não semi-private nem private | <cite index="43-1">blog</cite> + <cite index="38-1">editor's note atualizando a redação</cite> | Limita o Nível 5 |

### STRONGLY INFERRED

| # | Inferência | Base |
|---|---|---|
| I1 | O loop opera em **passos de variação discretos**, cada um sendo uma sessão de agente completa com múltiplas ações internas | Estrutura "500 direções → 40 commits" + descrição do loop no blog |
| I2 | A **commit policy é gated por correção** e só persiste o que não regride | C5 (razão 500:40) + abstract ("propor, reparar, criticar e **verificar**") |
| I3 | O lineage é **persistido de forma versionada e inspecionável pelo agente** (o agente "consulta o lineage atual") | C2 |
| I4 | O supervisor roda **fora do contexto do agente principal** (monitora "a trajetória mais ampla") | C8 |

### SPECULATIVE (não afirmar sem o PDF completo)

- Estrutura exata da memória (arquivos vs DB vs embeddings vs git).
- Prompt architecture e formato do handoff entre contextos.
- Critério numérico de detecção de estagnação.
- Modelo usado no supervisor e se difere do agente principal.
- Se há paralelização de candidatos.
- Política exata de seleção de pais / exploração vs exploração.

### REPRODUCTION-SPECIFIC (existe em `gatordevin/avo`, **não** provado na NVIDIA)

- `NOTES.md` como memória entre passos.
- Tags git `vN` com o score vector na mensagem de commit.
- `.avo/scores.jsonl`.
- Diretório `rejected/` arquivando diffs descartados.
- `--stagnation-window` com **default 3**.
- Modo sessão (usar a conversa Claude Code corrente como operador).
- Servidor MCP.

---

## 3. A ARMADILHA DOS 30% → 100% (e o fato de que a própria NVIDIA cai nela)

Você escreveu no prompt: *"DO NOT conclude: AVO increases Claude from 30% to 100%."* Está certo. Mas há uma ironia que precisa entrar no ledger:

**O subtítulo do próprio post da NVIDIA diz:** "The research project elevates Claude Opus 5 from a 30% model baseline to 100% as part of the complete AVO agent system."

E o corpo do mesmo post diz o oposto: <cite index="43-1">"Nossa execução usou a mesma família de modelo sob uma configuração de reasoning diferente e um sistema de agente e setup de avaliação substancialmente diferentes. Esses números portanto não devem ser interpretados como medida direta da contribuição de performance do AVO."</cite>

A imprensa amplificou o subtítulo, não o corpo: <cite index="35-1">"Claude Opus 5 scored 30% on ARC-AGI-3. Wrapped in Nvidia's AVO, it hit 100%"</cite>. Trate qualquer fonte que faça essa aritmética como não confiável.

**O que pode ser legitimamente comparado:**
1. **AVO vs VISTA em ações ambientais** (6.624 vs 7.542) — mesmo modelo, mesma tarefa, mesmos 183 níveis. Ainda assim confundido por backend/observação/memória, como a NVIDIA admite.
2. **Nada mais.** Não existe nenhuma comparação controlada publicada.

**Contexto adicional que muda a leitura do "100%":** <cite index="40-1">quando o benchmark lançou em março de 2026, humanos marcavam 100% e sistemas de IA de fronteira 0,51%. Até o fim de agosto, três harnesses purpose-built alcançaram o score perfeito no public set — Tycho no fim de julho, VISTA no início de agosto, e agora AVO.</cite>

Ou seja: **o public set do ARC-AGI-3 já foi saturado por três sistemas independentes.** Reproduzir 100% no public set não é mais um resultado — é entrar num clube de três. Isso destrói o Nível 5 do seu ladder como objetivo interessante.

---

## 4. AUDITORIA DA REPRODUÇÃO ABERTA (executada)

Clonei, inspecionei o código-fonte e rodei os testes.

```
48 passed in 3.32s
```

`avo doctor` reporta git/pyyaml/matplotlib/numpy OK e 4 targets prontos: `attention_c`, `attention_decode`, `attention_metal`, `game2048`.

### Matriz componente a componente

| Componente | Evidência NVIDIA | Implementação gatordevin | Fidelidade provável | Diferenças | Recomendação |
|---|---|---|---|---|---|
| Formulação `Vary(P_t)=Agent(P_t,K,f)` | C1, C2 | `prompts.py::build_variation_prompt` — recebe exatamente lineage, índice de KB e contrato de `f`; nunca diz qual versão olhar | **Alta** | Nenhuma detectada | Adotar |
| Ausência de `Sample`/`Generate` | C1 | Autor afirma: "não há `Sample` nem `Generate` em lugar nenhum deste código — esse é o ponto" | **Alta** | — | Adotar |
| Correctness gate | C2, I2 | `Score.from_eval_json` zera `primary` quando `correct=false` | **Alta** | — | Adotar |
| Commit policy | I2 | `Run.qualifies` — **matches-or-improves** (empate commita, permitindo refactor neutro que habilita ganho futuro) | **Média-alta** | A cláusula "matches" é citada como do paper; não pude verificar no PDF | Adotar, **marcar como a verificar** |
| Lineage | C2, I3 | Git standalone; cada versão aceita é commit taggeado `vN` com score vector na mensagem; `.avo/scores.jsonl` | **Média** | Mecanismo git é plausível mas o formato é escolha do autor | Adotar; é REPRODUCTION-SPECIFIC |
| Rejeitados | — | `Run.reject` reverte a work tree e arquiva o diff em `rejected/` | **Desconhecida** | Não há evidência NVIDIA | Manter — é bom design independentemente |
| Memória entre passos | C7 | `NOTES.md` + o próprio lineage | **Baixa** | C7 lista compiler/profiler output e "raciocínio acumulado"; `NOTES.md` é bem mais simples | **Maior gap.** Ver §5 |
| Supervisor | C8 | `supervisor_enabled`, `stagnation_window=3`, `supervisor_backend`, `supervisor_model` separados; `_run_supervisor` | **Média** | Janela=3 é escolha arbitrária do autor | Adotar como baseline **e ablacionar** |
| Knowledge base `K` | C2 | `knowledge.py` — diretório copiado para o run; framework fornece só um **índice** (path + primeiro heading), nunca faz retrieval pelo agente | **Média-alta** | Coerente com "agente decide o que estudar" | Adotar |
| Backends de agente | — | `agents/` com agent_sdk, api, claude_cli, mock | REPRODUCTION-SPECIFIC | — | Adotar (resolve Fase 15) |
| Modo sessão | — | Entrega o prompt à sessão Claude Code corrente; **sem API key, sem custo adicional** | REPRODUCTION-SPECIFIC | — | **Adotar — resolve Fase 19** |
| MCP server | — | `mcp_server.py` | REPRODUCTION-SPECIFIC | — | Opcional |
| ARC-AGI-3 | C9–C13 | **Ausente** | — | Nenhum target ARC | Não existe reprodução aberta do lado ARC |

### O achado mais importante da auditoria

O repositório resolve o problema que você levantou na Fase 19: *"não assuma que uma API key da Anthropic é necessária"*. O README afirma que o driver default **não** spawna agente e **não** chama API — entrega o prompt de variação à sessão Claude Code corrente. Modo unattended (spawn por passo, dias a fio, como o experimento de 7 dias) é opt-in justamente porque gasta quota.

Isso significa: **você pode rodar a máquina AVO completa hoje, na sua assinatura Max, custo marginal zero.**

---

## 5. GAP ANALYSIS

### PUBLICLY REPRODUCIBLE
Formulação `Agent(P_t,K,f)`; correctness gate; lineage git-backed; commit policy; interface de KB por índice; contrato do evaluator; interface de observação ARC (grid textual 64×64, ações sem descrição — C11/C12 são explícitos o bastante para implementar).

### PARTIALLY SPECIFIED
Supervisor (sabemos *o que* faz — C8 — não *como* detecta); commit policy (a cláusula "matches" precisa de verificação no PDF); seleção de pais.

### UNKNOWN / PROPRIETARY — e como transformar em experimento

**Gap 1 — Arquitetura de memória.** C7 diz *o que* sobrevive, nunca *como*. Hipóteses testáveis:
(a) arquivos markdown estruturados + git; (b) JSONL append-only + sumarização periódica; (c) memória hierárquica com sumários por nível; (d) embeddings/retrieval; (e) híbrido: lineage em git + episódico em JSONL + semântico em markdown curado.
**Experimento:** rodar o mesmo target com cada esquema, orçamento de tokens igualado, medir melhoria por iteração e taxa de re-exploração de becos já visitados.

**Gap 2 — Detecção de estagnação.** Hipóteses: (a) N passos sem commit (o repo usa 3); (b) sem melhoria relativa acima de ε; (c) similaridade de diffs entre tentativas recentes; (d) juízo do supervisor sobre o trace.
**Experimento:** varrer a janela em {1,3,5,10} + as variantes (b)/(c), medir commits por hora.

**Gap 3 — Contribuição de cada componente.** A NVIDIA **declarou explicitamente que não isolou** (C16). Não há ablação publicada em lugar nenhum.

---

## 6. ONDE ESTÁ O VALOR REAL DESTE PROJETO

Seu ladder de sucesso precisa ser reescrito, porque três dos seis níveis estão mortos na chegada:

| Nível | Veredito |
|---|---|
| 1 — Reprodução de mecanismo | ✅ Viável. Em grande parte **já feito** por `gatordevin/avo` |
| 2 — Reprodução comportamental | ✅ Viável e barato (target `game2048`, modo sessão) |
| 3 — Generalização | ✅ Viável. É o teste da tese C14: trocar só ambiente/ferramentas/evaluator |
| 4 — Reprodução de benchmark | ⚠️ Parcial. O lado kernel exige B200; o lado ARC exige construir a interface do zero |
| 5 — Reprodução de fronteira | ❌ **Morto.** O public set já foi saturado por 3 sistemas. 100% não prova mais nada |
| 6 — Melhoria | ✅ **É aqui que está tudo** |

**A contribuição real disponível:** a NVIDIA publicou uma arquitetura com 5+ componentes, declarou que dois deles são "particularmente importantes", e **admitiu por escrito que não mediu a contribuição individual de nenhum**. Ninguém fez essa ablação. Ela é barata (target sintético, sem GPU, modo sessão sem API), metodologicamente limpa (correção objetiva, score numérico) e diretamente publicável.

Isso conecta com o desenho experimental que já construímos nas rodadas anteriores: braços com **orçamento de tokens igualado**, seeds múltiplos, McNemar/bootstrap, Holm-Bonferroni. A diferença é que aqui a métrica é ainda melhor que pass@1 — é **melhoria de score por iteração sob orçamento fixo**, que é contínua e mais sensível.

---

## 7. PLANO MÍNIMO RECOMENDADO

**Não construa o OpenAVO Lab.** Ele já existe, tem 7.330 linhas, 48 testes verdes e um mapa explícito paper→código. Reescrevê-lo é reconstruir a parte fácil e resolvida.

**Estágio 0 (hoje, custo zero).** Rodar `game2048` em modo sessão. Objetivo: ver a máquina completa girar — variação → avaliação → gate de correção → commit → lineage → supervisor. **Gate:** o sistema supera autonomamente o candidato inicial. Isso é o seu Nível 2, hoje.

**Estágio 1 (dias, custo baixo).** Ablação sob orçamento igualado no `game2048` + um segundo target: `sem memória / sem supervisor / sem lineage / sem KB / AVO completo`. 5 seeds cada. **Este é o entregável científico.** Nenhum concorrente publicou isso.

**Estágio 2 (só se o Estágio 1 der sinal).** Testar C14 — a tese de generalidade — escrevendo um target novo em domínio distante (ex.: otimizar uma query SQL sob custo medido no seu Postgres). Se o mesmo harness funciona trocando só evaluator e ferramentas, você validou a afirmação central da NVIDIA de forma independente. **Isso é mais interessante que qualquer número de ARC.**

**Estágio 3 (opcional).** Interface ARC-AGI-3 com grid textual 64×64 (C11/C12 dão a especificação). Mas entre nisso sabendo que 100% no public set já não é notícia.

**Não construa:** interface ARC antes do Estágio 1; qualquer coisa com B200; reimplementação from-scratch do harness; os 15 arquivos de arquitetura do master prompt antes de ter dados.

---

## 8. RISCOS

| Risco | Mitigação |
|---|---|
| Atribuir à NVIDIA design que é do `gatordevin` | O ledger §2 separa; toda linha REPRODUCTION-SPECIFIC deve ser marcada em qualquer texto derivado |
| `game2048` ser fácil demais para diferenciar arquiteturas | Medir ceiling do baseline primeiro; se saturar, trocar de target antes de rodar a ablação |
| Ablação sem controle de tokens reproduzir o erro que a NVIDIA evitou | Igualar orçamento total de tokens entre braços — inclusive os do supervisor |
| Autonomia + execução de código | Sandbox obrigatório (Fase 20 do seu prompt está correta e não é opcional) |

---

## 9. RESOLUÇÕES APÓS LEITURA DO PDF COMPLETO (v0.2)

PDF lido integralmente. Reclassificações:

| Item | Antes | Agora | Citação literal (§) |
|---|---|---|---|
| `matches-or-improves` | Média-alta / a verificar | ✅ **CONFIRMADO NVIDIA** | §3.2: "persistimos uma nova versão commitada apenas quando ela passa nas checagens de correção **e iguala ou melhora** o score relativo à melhor versão commitada até então; tentativas intermediárias malsucedidas permanecem na trajetória interna de busca do agente mas não são adicionadas ao lineage commitado" |
| Lineage em git | Inferido | ✅ **CONFIRMADO NVIDIA** | §3.3: "Cada versão commitada é persistida como um commit git junto com seu score, mantendo continuidade total de estado" |
| **Estrutura de memória** | SPECULATIVE | ✅ **CONFIRMADO — e é trivial** | §4.1: "Mantém memória persistente **através do seu histórico de conversa**, que acumula o contexto completo de edições anteriores, saídas de compilador, resultados de profiling e raciocínio ao longo do processo evolutivo" |
| Seleção de pais / diversidade / branching | Assumido como existente (Fase 5) | ❌ **NÃO EXISTE** | §3.1/§3.3: instanciação em **linhagem única** a partir de seed x₀; "deixando branching em nível de população e gestão de arquivo para extensões futuras" |
| Agente | Desconhecido | ✅ CONFIRMADO como **não-público** | §4.1: "coding agent de propósito geral desenvolvido internamente, movido por LLMs de fronteira". "Nenhuma modificação específica de tarefa é feita no agente" |
| Detecção de estagnação (limiar) | SPECULATIVE | ⚠️ **CONTINUA SPECULATIVE** | §3.3 descreve só o comportamento ("revisa a trajetória e direciona para várias direções candidatas"). Nenhum limiar numérico. `stagnation_window=3` permanece REPRODUCTION-SPECIFIC |
| Ablação de componentes arquiteturais | Ausente | ✅ **CONFIRMADO AUSENTE** | Tabela 1 ablaciona apenas *otimizações descobertas* (v19→v20 etc.), nunca componentes do AVO |

**Consequência principal:** a "memória persistente" que o blog destaca como um dos dois mecanismos críticos é, no paper, **o histórico de conversa do agente**. Não é banco, não é embedding, não é grafo, não é sumarização hierárquica. O que de fato persiste de forma durável é o **lineage em git com scores**.

Dados adicionais do paper úteis para calibrar réplica:
- 40 versões / 7 dias; **cinco** pontos de inflexão arquitetural entre elas (v8, v13, v20, v30, v33); melhoria em **saltos discretos separados por platôs**, não gradual.
- Retornos decrescentes: v1–v20 dão os maiores ganhos absolutos; v21–v40 ganhos menores e compostos.
- Maior ganho isolado: branchless accumulator rescaling (v19→v20), **+8,1%** non-causal.
- Trabalho irmão citado: **VibeTensor: System Software for Deep Learning, Fully Generated by AI Agents** (Xu, Chen et al., NVIDIA, 2026) — mesma equipe, vale investigar.

### Ainda não verificado
- VISTA e Tycho em profundidade.
- Metodologia RHAE do ARC Prize.
- Execução dos targets (só rodei os testes unitários).
- `DRIVING.md`, `TARGETS.md`, `mcp_server.py`, `agents/` em detalhe.
- Código-fonte oficial NVIDIA: §4.1 confirma que o agente é interno — **provavelmente não existe versão pública**.

---

## 10. O PRÉ-REQUISITO QUE ESTE RELATÓRIO NÃO TINHA (v0.3, medido)

A §6 diz que a contribuição real disponível é a ablação que a NVIDIA não fez, e
a §7 recomenda executá-la no Estágio 1 com cinco braços e cinco sementes. As duas
coisas continuam certas. Falta uma condição entre elas, e ela não é barata de
descobrir: **o alvo precisa ser capaz de distinguir os braços.**

Rodamos os dois experimentos. A ablação de componentes
(`experiments/ABLATION.md`, US$ 168) não distinguiu nada. O controle honesto
(`experiments/CONTROLE.md`, US$ 175) também não — e explicou por quê:

> Uma sessão de agente **morta aos 106 segundos**, custando **US$ 0,53**, mediu
> **4,55×** no alvo de referência. O AVO completo, com 23× mais relógio e 22×
> mais dinheiro, mediu 4,92×. A sessão de cem segundos capturou **68% de todo o
> ganho disponível** sozinha.

Não sobrou espaço onde as arquiteturas pudessem diferir. Com o desvio observado,
distinguir os braços pediria de 49 a 246 sementes por braço — **US$ 1.770 a
US$ 7.400 por comparação**, e isso num alvo onde a diferença real, se existe, é
menor que a variação entre sementes.

**Isto vale para o Estágio 1 como recomendado.** O `game2048` do upstream é um
alvo cujo espaço de busca um agente competente com o avaliador na mão percorre
numa sessão. Rodar cinco braços × cinco sementes nele produziria exatamente os
intervalos que contêm zero que nós produzimos, por um custo parecido. O Estágio 1
não estava errado; estava incompleto.

**O conserto é uma checagem de US$ 0,50.** `docs/TARGET_DESIGN.md` §3e define a
propriedade — uma sessão única não pode esgotar o headroom —,
`experiments/ablacao/sonda.py` a mede, e o `avo-lab verify` a cobra. Medida nos
cinco alvos deste repositório, **só o `sql_agg` sobrevive**: a sonda pega 49% do
ganho disponível e sobra 51% para a busca disputar.

**O que isso não é.** Não é evidência contra a arquitetura da NVIDIA. O regime
do paper são centenas de iterações num espaço que nenhuma sessão esgota — kernels
de atenção em B200 —, e um alvo que uma sessão esgota em cem segundos está fora
desse regime por construção. Um resultado nulo nele é uma afirmação sobre o alvo,
e a distinção entre as duas coisas é a única razão de este documento existir.

**O que isso muda no ladder da §6.** O nível 6 — "melhoria", onde estaria tudo —
ganha um degrau anterior que ninguém tinha enunciado: **construir um alvo onde a
pergunta seja mensurável**. É mais difícil que construir a ablação, custa quase
nada em dinheiro, e é onde o valor está agora.

---

## 11. ERRATA À §10 — os agentes estavam cegos (v0.4)

A §10 conclui que o alvo é o gargalo, e essa conclusão fica de pé. A evidência
que ela usa, porém, era pior do que eu sabia: nos dois experimentos citados
(US$ 343), **nenhum agente conseguiu executar o avaliador**. Detalhes em
`experiments/CONTROLE.md`, no topo, e a falha 8 do README.

Duas consequências, em direções opostas:

**A favor da §10.** O argumento fica mais forte. Se um agente que não pode medir
nada captura 68% do headroom disponível em cem segundos, o alvo é ainda mais
trivial do que a §10 afirmou: a knowledge base entrega a resposta, e verificar é
dispensável. É o caso mais claro possível de um alvo que não discrimina.

**Contra o resto.** Qualquer afirmação sobre a *arquitetura* fica suspensa. O
loop que rodou não é o do abstract (C2), que descreve o agente consultando
"lineage, knowledge base e **feedback de execução**" para "propor, reparar,
**criticar e verificar**". Sem o avaliador, os dois últimos verbos não
aconteciam dentro do passo. O `full` manteve o feedback entre passos, via
harness e gate; o que faltou foi o ciclo interno.

**O que isto adiciona ao ledger.** Uma categoria que não estava lá e que vale
para qualquer reprodução deste paper:

> **VERIFICADO NA EXECUÇÃO** — o que a transcrição do agente prova que ele
> conseguiu fazer, por oposição ao que a configuração diz que ele podia fazer.

As duas coisas divergiram aqui por dois experimentos inteiros, e a diferença não
apareceu em nenhuma métrica: os runs terminavam com exit 0, score positivo,
correção verificada e commits aceitos. Só apareceu no texto que os agentes
escreveram sobre a própria sessão. Agora é `ABLATION_PROTOCOL.md` §4 e um
comando que sai com código 1.
