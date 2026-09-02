"""Destila as transcrições brutas do `greedy` no que merece sobreviver.

As transcrições stream-json são megabytes por sessão e ficam fora do git
(`.gitignore`). O que tem valor de registro nelas é pequeno: o que o agente
DISSE ter feito, na linha `RESUMO:` que o prompt pede, e quantas vezes ele
chamou o avaliador — que é a única medida direta de quão empírico ele foi.

Isso importa para ler o resultado. Um braço que mede muito e um que mede pouco
chegam ao mesmo score por caminhos diferentes, e a diferença aparece aqui e em
nenhum outro lugar do `greedy.jsonl`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

AQUI = Path(__file__).resolve().parent


def _texto(ev: dict) -> str:
    msg = ev.get("message") or {}
    partes = msg.get("content") if isinstance(msg.get("content"), list) else []
    return "\n".join(p.get("text", "") for p in partes if isinstance(p, dict))


def destila(caminho: Path) -> dict:
    resumos: list[str] = []
    avaliacoes = 0
    edicoes = 0
    for linha in caminho.read_text(encoding="utf-8", errors="replace").splitlines():
        if not linha.strip():
            continue
        try:
            ev = json.loads(linha)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "assistant":
            for parte in (ev.get("message") or {}).get("content") or []:
                if not isinstance(parte, dict):
                    continue
                if parte.get("type") == "tool_use":
                    nome = parte.get("name")
                    entrada = json.dumps(parte.get("input") or {}, ensure_ascii=False)
                    if nome == "Bash" and "avo-eval" in entrada:
                        avaliacoes += 1
                    elif nome in ("Edit", "Write", "MultiEdit"):
                        edicoes += 1
            texto = _texto(ev)
            for bloco in texto.splitlines():
                if bloco.strip().startswith("RESUMO:"):
                    resumos.append(bloco.strip())
    return {
        "sessao": caminho.stem,
        "avaliacoes": avaliacoes,
        "edicoes": edicoes,
        "resumos": resumos,
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Destila as transcricoes do greedy")
    p.add_argument("--logs", default=str(AQUI / "resultados" / "logs"))
    p.add_argument("--saida", default=str(AQUI / "resultados" / "resumos.jsonl"))
    args = p.parse_args()

    origem = Path(args.logs)
    if not origem.is_dir():
        print(f"sem transcricoes em {origem}")
        return 1
    linhas = [destila(x) for x in sorted(origem.glob("*.jsonl"))]
    Path(args.saida).write_text(
        "".join(json.dumps(d, ensure_ascii=False) + "\n" for d in linhas), encoding="utf-8"
    )
    print(f"{'sessao':>22} {'avaliacoes':>11} {'edicoes':>8} {'resumos':>8}")
    for d in linhas:
        print(f"{d['sessao']:>22} {d['avaliacoes']:>11} {d['edicoes']:>8} {len(d['resumos']):>8}")
    print(f"\n-> {args.saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
