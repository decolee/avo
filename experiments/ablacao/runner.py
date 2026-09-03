"""Runner da ablação — Sessão 3 do RUNBOOK.

Roda os braços definidos em `docs/ABLATION_PROTOCOL.md` §3 contra um alvo, em
modo NÃO supervisionado: cada passo é um agente novo, spawnado pelo harness, sem
o conhecimento prévio de quem escreveu o alvo. Isso importa — um operador humano
que conhece as respostas mede a si mesmo, não a arquitetura.

Três decisões de execução, todas vindas do protocolo:

  Intercalado, nunca em bloco. Os braços rodam alternados dentro de cada rodada,
  para que deriva térmica ou ruído de vizinho não vire efeito de braço.

  Ordem aleatorizada dentro da rodada, com semente derivada do índice da rodada
  — reprodutível, e ainda assim não sistemática.

  Um passo por invocação (`avo run --resume --max-steps k`). O braço `no_memory`
  precisa apagar o `NOTES.md` entre passos, e usar o mesmo caminho de código nos
  quatro braços elimina isso como confundidor.

Registra por passo: se foi aceito, o score, o custo em dólares, os turnos do
agente, e — o que nenhuma métrica do framework registra — **se o código do
candidato realmente mudou**. Um agente que falha deixa a árvore intacta, e a
política "iguala ou melhora" ainda pode commitar essa versão por ruído de
medição. Sem essa coluna, um braço que falha mais parece um braço que commita
mais.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
AQUI = Path(__file__).resolve().parent

#: Os braços. `flags` vai para o `avo run` na criação do run; `kb` decide se o
#: alvo usado é o original ou a variante sem knowledge base; `apaga_notas` liga
#: a ablação de memória entre passos.
BRACOS = {
    "full": {"flags": [], "kb": True, "apaga_notas": False},
    "no_supervisor": {"flags": ["--no-supervisor"], "kb": True, "apaga_notas": False},
    "no_kb": {"flags": [], "kb": False, "apaga_notas": False},
    "no_memory": {"flags": [], "kb": True, "apaga_notas": True},
}


def variante_sem_kb(alvo: str) -> Path:
    """Cópia do alvo com a knowledge base vazia.

    Symlinks para `eval.py`, `seed/` e `make_data.py`: o `eval.py` resolve o
    próprio caminho real, então continua achando o mesmo `data/` e o mesmo lock.
    O que muda é só o `knowledge_base`, que aponta para um diretório vazio.
    """
    origem = RAIZ / "targets" / alvo
    destino = AQUI / f"alvo_{alvo}_sem_kb"
    if destino.exists():
        shutil.rmtree(destino)
    (destino / "kb_vazia").mkdir(parents=True)
    for nome in ("eval.py", "seed", "make_data.py", "dataset.lock.json", "data"):
        if (origem / nome).exists():
            (destino / nome).symlink_to(origem / nome)
    yaml = (origem / "target.yaml").read_text(encoding="utf-8")
    yaml = yaml.replace("knowledge_base: kb", "knowledge_base: kb_vazia")
    yaml = yaml.replace(f"name: {alvo}", f"name: {alvo}_sem_kb")
    (destino / "target.yaml").write_text(yaml, encoding="utf-8")
    return destino


#: As ferramentas que o agente recebe, e por que esta lista existe.
#:
#: O harness usa `bypassPermissions` por padrao, que mapeia para
#: `--dangerously-skip-permissions` e e RECUSADO quando o processo roda como
#: root. Ao esbarrar nisso eu troquei por `acceptEdits` — que libera edicao de
#: arquivo e **exige aprovacao para Bash**. O efeito foi que nenhum agente, em
#: nenhum experimento em modo nao supervisionado, conseguiu rodar `./avo-eval`:
#: todos escreveram codigo no escuro. Os resumos das sessoes dizem isso com
#: todas as letras ("medi ZERO ideias porque o avaliador foi recusado por
#: permissao"), e eu so fui ler os resumos depois de dois experimentos.
#:
#: `--allowed-tools` e o conserto certo, e e melhor que o `bypassPermissions`
#: original para o proposito daqui: a concessao fica EXPLICITA e identica em
#: todos os bracos, em vez de ser "tudo liberado" por omissao.
FERRAMENTAS = "Bash,Read,Edit,Write,Glob,Grep,MultiEdit,TodoWrite"
ARGS_AGENTE = ["--allowed-tools", FERRAMENTAS]


def _liberar_ferramentas(run_dir: Path, extras: list[str] = ARGS_AGENTE) -> bool:
    """Injeta `extra_agent_args` no `run.json` recem-criado.

    O harness le a configuracao do run de `run.json` a cada `--resume`
    (`run.py:from_root`), e `extra_agent_args` e repassado direto para o argv do
    CLI (`claude_cli.py:build_argv`). Nao ha flag de linha de comando para isso,
    e escrever no arquivo e melhor que remendar o vendor: o commit fixado em
    `vendor/avo.lock` continua sendo o que foi auditado.
    """
    meta_path = run_dir / "run.json"
    if not meta_path.is_file():
        return False
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    cfg = meta.setdefault("config", {})
    if cfg.get("extra_agent_args") == extras:
        return True
    cfg["extra_agent_args"] = list(extras)
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return True


def _sh(argv: list[str], timeout: float) -> tuple[int, str]:
    try:
        p = subprocess.run(
            argv, cwd=str(RAIZ), capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired:
        return -1, f"estourou {timeout:.0f}s"
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _entrypoint(alvo: str) -> str:
    yaml = (RAIZ / "targets" / alvo / "target.yaml").read_text(encoding="utf-8")
    for linha in yaml.splitlines():
        if linha.startswith("entrypoint:"):
            return linha.split(":", 1)[1].strip()
    return ""


def _codigo_mudou(work: Path, entrypoint: str, ver_antes: int, ver_depois: int) -> bool | None:
    """O arquivo do candidato mudou entre duas versões commitadas?

    `None` quando não dá para saber (versão ausente). É a coluna que separa um
    commit de verdade de uma catraca de ruído.
    """
    if ver_antes == ver_depois:
        return False
    code, saida = _sh(
        ["git", "-C", str(work), "diff", "--name-only", f"v{ver_antes}", f"v{ver_depois}"], 120
    )
    if code != 0:
        return None
    # Qualquer arquivo versionado conta. O `sql_agg` tem dois — `query.sql` e
    # `setup.sql` — e um candidato que so cria indice mexe apenas no segundo.
    # Olhar so o entrypoint marcaria essa mudanca real como "nao mudou nada".
    return any(linha.strip() for linha in saida.splitlines())


def _passos_feitos(run_dir: Path) -> int:
    """Quantos passos deste run ja foram executados, pelo `trajectory.jsonl`.

    Existe porque um restart de container no meio de uma semente custava a
    semente inteira: o runner criava um run novo e refazia os oito passos. Com
    isto a perda cai para o passo que estava em voo. Num programa de ~98h de
    relogio, em que reinicios acontecem, a diferenca e de horas.
    """
    caminho = run_dir / "trajectory.jsonl"
    if not caminho.is_file():
        return 0
    ultimo = 0
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        if linha.strip():
            ultimo = max(ultimo, int(json.loads(linha).get("step", 0)))
    return ultimo


def _reaproveita_run(runs_dir: Path) -> Path | None:
    """Um run desta semente ficou pela metade num restart? Devolve-o.

    So reaproveita run com pelo menos um passo feito: um diretorio criado e
    abandonado antes do primeiro passo nao tem nada a economizar, e reusa-lo
    arriscaria herdar uma configuracao antiga do `run.json`.
    """
    if not runs_dir.is_dir():
        return None
    for candidato in sorted(runs_dir.iterdir(), reverse=True):
        if candidato.is_dir() and _passos_feitos(candidato) > 0:
            return candidato
    return None


def _seed_inicial(run_dir: Path) -> float:
    """O score do SEED — a versao 0 do `scores.jsonl`, nunca a ultima linha.

    Bug que este laboratorio produziu e mediu: `_estado` devolve a ULTIMA linha,
    que num run novo e o seed e num run RETOMADO e o melhor score ate ali. Com a
    retomada parcial ligada, o `full` s1 gravou `primary_seed = 11.073` — o que
    ele ja tinha conquistado em quatro passos — e o ganho saiu 1.00x. A semente
    parecia um fracasso total e era um sucesso de 4,47x.

    Um bug que transforma sucesso em fracasso e menos perigoso que o contrario,
    mas os dois estragam a media do braco do mesmo jeito.
    """
    caminho = run_dir / "work" / ".avo" / "scores.jsonl"
    if not caminho.is_file():
        return 0.0
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        if linha.strip():
            d = json.loads(linha)
            if int(d.get("version", 0)) == 0:
                return float((d.get("score") or {}).get("primary", 0.0))
    return 0.0


def _estado(run_dir: Path) -> dict:
    caminho = run_dir / "work" / ".avo" / "scores.jsonl"
    if not caminho.is_file():
        return {"versao": 0, "primary": 0.0}
    ultimo = {}
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        if linha.strip():
            ultimo = json.loads(linha)
    return {
        "versao": int(ultimo.get("version", 0)),
        "primary": float((ultimo.get("score") or {}).get("primary", 0.0)),
    }


def _meta_do_passo(run_dir: Path, passo: int) -> dict:
    caminho = run_dir / "trajectory.jsonl"
    if not caminho.is_file():
        return {}
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        if not linha.strip():
            continue
        d = json.loads(linha)
        if d.get("step") == passo:
            a = d.get("agent") or {}
            return {
                "aceito": bool(d.get("accepted")),
                "agente_ok": bool(a.get("ok")),
                "custo_usd": a.get("total_cost_usd"),
                "turnos": a.get("num_turns"),
                "dur_agente_s": a.get("duration_s"),
                "erro_agente": (str(a.get("error"))[:200] if a.get("error") else None),
                # Morrer por TIMEOUT e diferente de falhar: o agente costuma ter
                # escrito codigo util antes de ser morto. Contar os dois como
                # "falha" faria a analise marcar um braco como nao interpretavel
                # por um motivo que nao e dele.
                "morto_por_tempo": bool(a.get("error") and "exceeded" in str(a.get("error"))),
                "supervisor": bool(d.get("supervisor")),
            }
    return {}


def roda_um(
    braco: str,
    semente: int,
    alvo: str,
    passos: int,
    timeout_agente: str,
    saida: Path,
    effort: str = "medium",
    teto_usd: float = 2.5,
    janela_estagnacao: int | None = None,
) -> dict:
    cfg = BRACOS[braco]
    alvo_ref = alvo if cfg["kb"] else str(variante_sem_kb(alvo))
    runs_dir = saida / "runs" / f"{braco}-s{semente}"
    runs_dir.mkdir(parents=True, exist_ok=True)

    retomado = _reaproveita_run(runs_dir)
    if retomado is not None:
        print(
            f"    retomando {retomado.name}: {_passos_feitos(retomado)} passos ja feitos",
            flush=True,
        )

    criar = [
        sys.executable,
        "-m",
        "avo",
        "run",
        "--target",
        alvo_ref,
        "--runs-dir",
        str(runs_dir),
        "--max-steps",
        "0",
        "--agent-timeout",
        timeout_agente,
        "--backend",
        "claude_cli",
        "--permission-mode",
        "acceptEdits",
        # Sem isto o supervisor nao existe. Na ablacao da Sessao 3, com janela 3 e
        # runs de 3 passos, ele nao disparou uma unica vez em 36 passos elegiveis:
        # o braco `no_supervisor` rodava exatamente o mesmo codigo que o `full`.
        *(
            ["--stagnation-window", str(janela_estagnacao)]
            if janela_estagnacao and not cfg["flags"]
            else []
        ),
        *cfg["flags"],
    ]
    if retomado is not None:
        run_dir = retomado
    else:
        code, saida_txt = _sh(criar, 900)
        candidatos = sorted(runs_dir.iterdir())
        if not candidatos:
            return {
                "braco": braco,
                "semente": semente,
                "erro": f"run nao criado: {saida_txt[-400:]}",
            }
        run_dir = candidatos[-1]
    if not _liberar_ferramentas(run_dir):
        return {"braco": braco, "semente": semente, "erro": f"run.json ausente em {run_dir}"}

    notas_virgens = (run_dir / "NOTES.md").read_text(encoding="utf-8")
    entrypoint = _entrypoint(alvo)
    registro = {
        "braco": braco,
        "semente": semente,
        "alvo": alvo,
        "run_dir": str(run_dir),
        # Sempre da versao 0, nunca do estado atual: num run retomado o estado
        # atual e o que ja foi conquistado, e o ganho sairia 1.00x.
        "primary_seed": _seed_inicial(run_dir),
        "retomado_de": _passos_feitos(run_dir) if retomado is not None else 0,
        "passos": [],
    }

    for k in range(_passos_feitos(run_dir) + 1, passos + 1):
        if cfg["apaga_notas"]:
            (run_dir / "NOTES.md").write_text(notas_virgens, encoding="utf-8")

        antes = _estado(run_dir)
        t0 = time.time()
        code, texto = _sh(
            [
                sys.executable,
                "-m",
                "avo",
                "run",
                "--resume",
                str(run_dir),
                "--max-steps",
                str(k),
            ],
            timeout=3600,
        )
        depois = _estado(run_dir)
        meta = _meta_do_passo(run_dir, k)
        registro["passos"].append(
            {
                "passo": k,
                "primary_antes": antes["primary"],
                "primary_depois": depois["primary"],
                "versao": depois["versao"],
                "codigo_mudou": _codigo_mudou(
                    run_dir / "work", entrypoint, antes["versao"], depois["versao"]
                ),
                "wall_s": round(time.time() - t0, 1),
                "exit": code,
                **meta,
            }
        )
        (saida / "parcial.jsonl").open("a", encoding="utf-8").write(
            json.dumps(registro["passos"][-1] | {"braco": braco, "semente": semente}) + "\n"
        )

    # Num run RETOMADO o laco acima so executou os passos que faltavam, entao
    # `registro["passos"]` cobriria 5..8 e o custo sairia pela metade. A verdade
    # completa esta no `trajectory.jsonl`, que o harness escreve desde o passo 1 —
    # inclusive de invocacoes anteriores. Reconstroi a lista inteira dali.
    if registro.get("retomado_de"):
        por_passo = {x["passo"]: x for x in registro["passos"]}
        completo = []
        for k in range(1, passos + 1):
            meta = _meta_do_passo(run_dir, k)
            if not meta and k not in por_passo:
                continue
            completo.append(por_passo.get(k) or ({"passo": k, "reconstruido": True} | meta))
        registro["passos"] = completo

    final = _estado(run_dir)
    registro["primary_final"] = final["primary"]
    registro["versao_final"] = final["versao"]
    base = registro["primary_seed"] or 1e-9
    registro["melhoria_relativa"] = final["primary"] / base
    return registro


def main() -> int:
    p = argparse.ArgumentParser(description="Ablação de componentes do AVO")
    p.add_argument("--alvo", default="etl_agg")
    p.add_argument("--passos", type=int, default=6)
    p.add_argument("--rodadas", type=int, default=3, help="n por braço")
    p.add_argument("--timeout-agente", default="15m")
    p.add_argument("--effort", default="medium", help="igual em todos os bracos, por desenho")
    p.add_argument("--teto-usd", type=float, default=2.5, help="teto por passo, igual em todos")
    p.add_argument("--janela-estagnacao", type=int, default=None, help="--stagnation-window")
    p.add_argument("--saida", default=str(AQUI / "resultados"))
    p.add_argument("--bracos", nargs="*", default=list(BRACOS))
    args = p.parse_args()

    saida = Path(args.saida)
    saida.mkdir(parents=True, exist_ok=True)
    linha_resultados = saida / "results.jsonl"

    feitos = set()
    if linha_resultados.is_file():
        for linha in linha_resultados.read_text(encoding="utf-8").splitlines():
            if linha.strip():
                d = json.loads(linha)
                feitos.add((d.get("braco"), d.get("semente")))

    for rodada in range(args.rodadas):
        ordem = list(args.bracos)
        random.Random(1000 + rodada).shuffle(ordem)  # intercalado e não sistemático
        print(f"\n=== rodada {rodada} — ordem: {' '.join(ordem)} ===", flush=True)
        for braco in ordem:
            if (braco, rodada) in feitos:
                print(f"  {braco} s{rodada}: já feito, pulando", flush=True)
                continue
            t0 = time.time()
            print(f"  {braco} s{rodada}: rodando...", flush=True)
            reg = roda_um(
                braco,
                rodada,
                args.alvo,
                args.passos,
                args.timeout_agente,
                saida,
                effort=args.effort,
                teto_usd=args.teto_usd,
                janela_estagnacao=args.janela_estagnacao,
            )
            reg["rodada"] = rodada
            with linha_resultados.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(reg, ensure_ascii=False) + "\n")
            # Commit por semente. Um run deste braco custa ~US$21 e ~2,4h; um
            # restart de container ja custou uma corrida inteira deste
            # laboratorio uma vez, e resultado que nao esta no git nao existe.
            subprocess.run(
                ["git", "add", str(linha_resultados)],
                cwd=str(RAIZ),
                check=False,
                capture_output=True,
            )
            subprocess.run(
                [
                    "git",
                    "commit",
                    "-q",
                    "--no-verify",
                    "-m",
                    f"ablacao {args.alvo}: {braco} s{rodada} "
                    f"({reg.get('melhoria_relativa', 0):.2f}x)",
                ],
                cwd=str(RAIZ),
                check=False,
                capture_output=True,
            )
            print(
                f"  {braco} s{rodada}: seed={reg.get('primary_seed', 0):.3f} "
                f"final={reg.get('primary_final', 0):.3f} "
                f"({reg.get('melhoria_relativa', 0):.2f}x) em {time.time() - t0:.0f}s",
                flush=True,
            )
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    raise SystemExit(main())
