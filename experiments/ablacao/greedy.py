"""O braço de controle honesto: `greedy` — o mesmo modelo, sem estrutura AVO.

`docs/ABLATION_PROTOCOL.md` §3 chama isto de braço de controle honesto e diz por
que ele importa mais que qualquer ablação de componente: se a máquina completa
empatar com "o mesmo modelo, o mesmo `f`, e nenhuma estrutura", então a pergunta
sobre a contribuição de memória, KB ou supervisão fica muito menos interessante.

O que `greedy` RECEBE, igual ao `full`:
  - o mesmo seed `x_0`, na mesma árvore de trabalho
  - a mesma knowledge base
  - o mesmo avaliador (`./avo-eval`), que ele pode chamar à vontade
  - o mesmo objetivo, copiado do `agent.goal` do `target.yaml`
  - o mesmo modelo e o mesmo nível de esforço

O que `greedy` NÃO recebe — e é exatamente a estrutura do AVO:
  - lineage: nenhum histórico de versões commitadas com score
  - gate persistente: nada reverte uma regressão automaticamente
  - supervisor: ninguém observa a trajetória nem redireciona
  - memória entre passos: não há passos; é uma sessão só

A escolha de dar o avaliador ao `greedy` é deliberada. Sem ele o baseline seria
um espantalho — "modelo sem feedback nenhum" perde de qualquer coisa e não
ensina nada. Com ele, o baseline é o que um engenheiro competente faria com um
benchmark na mão, que é o padrão contra o qual a estrutura precisa se justificar.

O score é o do estado final da árvore de trabalho, medido pelo mesmo `eval.py`.
Se o `greedy` terminar numa regressão, isso conta — não ter reversão automática
é uma propriedade real de não ter a estrutura, e não uma pegadinha.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent


def _goal_do_alvo(alvo: str) -> tuple[str, str]:
    """Objetivo e notas, copiados do `target.yaml` — a mesma orientação do `full`."""
    import yaml

    data = yaml.safe_load((RAIZ / "targets" / alvo / "target.yaml").read_text(encoding="utf-8"))
    agente = data.get("agent") or {}
    return str(agente.get("goal") or ""), str(agente.get("notes") or "")


#: Os dois perfis do controle. A diferença é só a instrução de parada, e ela
#: existe porque a calibração mostrou que o greedy natural PARA sozinho em ~12
#: min — bem antes do orçamento. Comparar só o natural contra o `full` daria ao
#: `full` quatro vezes mais compute e a crítica seria justa. Comparar só o
#: persistente esconderia o comportamento default, que é o que um engenheiro
#: realmente obtém quando pede "otimize isso". Os dois são o experimento.
PERFIS = ("natural", "persistente")

_PARADA = {
    "natural": """Trabalhe ate acabar o tempo ou ate nao conseguir mais melhorar. Termine com uma
linha comecando com RESUMO: dizendo o que voce fez e o ultimo score medido.""",
    "persistente": """Nao pare antes de gastar o orcamento. Quando uma linha de ataque se esgotar,
procure outra: releia a kb, meca de novo onde esta o custo, tente uma abordagem
diferente da que voce ja tentou. "Nao consigo melhorar mais" so vale depois de
voce ter medido pelo menos tres ideias distintas e nenhuma ter passado do ruido.

Guarde a MELHOR versao que voce mediu. Nao ha reversao automatica aqui: se uma
tentativa piorar o score, e sua responsabilidade desfazer antes de terminar. O
que estiver no arquivo no fim e o que conta.

Termine com uma linha comecando com RESUMO: dizendo o que voce fez, quantas
ideias mediu, e o ultimo score medido.""",
}


def monta_prompt(alvo: str, run_dir: Path, orcamento_min: int, perfil: str = "natural") -> str:
    goal, notes = _goal_do_alvo(alvo)
    entrypoint = ""
    import yaml

    data = yaml.safe_load((RAIZ / "targets" / alvo / "target.yaml").read_text(encoding="utf-8"))
    entrypoint = str(data.get("entrypoint") or "")

    return f"""Voce esta em {run_dir}.

Otimize `work/{entrypoint}` para maximizar o score. Voce tem ate {orcamento_min}
minutos.

## O objetivo

{goal}

## O que voce precisa saber

{notes}

## Como medir

`./avo-eval --text` deste diretorio roda o avaliador sobre o que estiver em
`work/` e imprime o score e as metricas por regime. Use a vontade — e a mesma
funcao que decide o resultado final.

A knowledge base esta em `kb/`. Leia o que achar util.

## Como voce sera avaliado

O score do ESTADO FINAL de `work/{entrypoint}`, medido pelo mesmo `./avo-eval`.
Nao ha commit, nao ha versoes, nao ha reversao automatica: o que estiver no
arquivo quando voce terminar e o que conta. Se voce piorar e nao desfazer, o
score piora.

{_PARADA[perfil]}
"""


def roda_greedy(
    alvo: str,
    run_dir: Path,
    timeout_s: float,
    effort: str,
    log: Path,
    perfil: str = "natural",
) -> dict:
    """Uma sessao unica de agente, sem estrutura. Devolve metadados da execucao."""
    orcamento_min = int(timeout_s // 60)
    prompt = monta_prompt(alvo, run_dir, orcamento_min, perfil)
    argv = [
        "claude",
        "-p",
        prompt,
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-mode",
        "acceptEdits",
        "--model",
        "claude-opus-5",
        "--effort",
        effort,
    ]
    log.parent.mkdir(parents=True, exist_ok=True)
    inicio = time.time()
    meta: dict = {"backend": "claude_cli_greedy", "model": "claude-opus-5", "perfil": perfil}
    with open(log, "a", encoding="utf-8") as fh:
        proc = subprocess.Popen(
            argv,
            cwd=str(run_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        estourou = False
        try:
            assert proc.stdout is not None
            prazo = inicio + timeout_s
            for linha in proc.stdout:
                fh.write(linha)
                fh.flush()
                try:
                    ev = json.loads(linha)
                except json.JSONDecodeError:
                    continue
                if ev.get("type") == "result":
                    for k in ("total_cost_usd", "num_turns", "is_error"):
                        if k in ev:
                            meta[k] = ev[k]
                if time.time() > prazo:
                    estourou = True
                    proc.kill()
                    break
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            estourou = True
            proc.kill()
    meta["duration_s"] = time.time() - inicio
    meta["morto_por_tempo"] = estourou
    meta["ok"] = not estourou and not meta.get("is_error")
    return meta


def avalia(alvo: str, workdir: Path) -> dict:
    """Score do estado final, pelo mesmo eval.py que julga o `full`."""
    out = subprocess.run(
        [sys.executable, f"targets/{alvo}/eval.py", "--workdir", str(workdir)],
        cwd=str(RAIZ),
        capture_output=True,
        text=True,
        timeout=1800,
        check=False,
    ).stdout
    linha = next(
        (x for x in reversed(out.splitlines()) if x.strip().startswith("AVO_RESULT:")), None
    )
    if not linha:
        return {"correct": False, "metrics": {}, "error": "avaliador nao emitiu AVO_RESULT"}
    return json.loads(linha.split("AVO_RESULT:", 1)[1])


def primary(payload: dict) -> float:
    import math

    if not payload.get("correct"):
        return 0.0
    vals = [v for v in (payload.get("metrics") or {}).values() if v > 0]
    return math.exp(sum(math.log(v) for v in vals) / len(vals)) if vals else 0.0
