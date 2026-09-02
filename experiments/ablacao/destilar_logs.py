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


_RECUSA = ("requires approval", "requires permission", "permission to use", "denied")

#: Como se reconhece uma invocacao do avaliador na transcricao.
_CHAMA_AVALIADOR = ("avo-eval", "eval.py")

#: Como se reconhece que ela DEU CERTO: o avaliador emite `AVO_RESULT:` no
#: stdout, e o modo `--text` imprime as medianas por regime.
_SAIDA_DO_AVALIADOR = ("avo_result", "medianas:")


def destila(caminho: Path) -> dict:
    """Le uma transcricao stream-json e devolve o que merece sobreviver a ela.

    A parte que importa e distinguir **tentou medir** de **mediu**. Elas sao
    correlacionadas por `tool_use_id`: o turno do assistente registra a
    INTENCAO de chamar a ferramenta, e o turno de usuario seguinte traz o
    resultado — que pode ser a saida do avaliador ou uma recusa de permissao.

    Contar so a intencao foi o erro que fez as 21 sessoes do controle no
    `csv_normalize` parecerem ter medido de 5 a 62 vezes cada, quando nenhuma
    delas mediu uma unica vez. E casar o texto do resultado sem olhar de qual
    chamada ele veio e o erro seguinte: um `Read` de `logs/eval.log` contem
    "medianas:" e nao e medicao nenhuma.
    """
    resumos: list[str] = []
    tentativas = 0
    medicoes = 0
    recusas = 0
    edicoes = 0
    pendentes: dict[str, bool] = {}  # tool_use_id -> era chamada ao avaliador

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
                    entrada = json.dumps(parte.get("input") or {}, ensure_ascii=False).lower()
                    if nome == "Bash" and any(x in entrada for x in _CHAMA_AVALIADOR):
                        tentativas += 1
                        pendentes[str(parte.get("id"))] = True
                    elif nome in ("Edit", "Write", "MultiEdit"):
                        edicoes += 1
                elif parte.get("type") == "text":
                    for bloco in parte.get("text", "").splitlines():
                        if bloco.strip().startswith("RESUMO:"):
                            resumos.append(bloco.strip())

        elif ev.get("type") == "user":
            for parte in (ev.get("message") or {}).get("content") or []:
                if not isinstance(parte, dict) or parte.get("type") != "tool_result":
                    continue
                if not pendentes.pop(str(parte.get("tool_use_id")), False):
                    continue  # resultado de outra ferramenta; nao diz nada sobre medicao
                corpo = json.dumps(parte.get("content") or "", ensure_ascii=False).lower()
                if parte.get("is_error") or any(x in corpo for x in _RECUSA):
                    recusas += 1
                elif any(x in corpo for x in _SAIDA_DO_AVALIADOR):
                    medicoes += 1

    return {
        "sessao": caminho.stem,
        "tentativas_avaliador": tentativas,
        "medicoes": medicoes,
        "recusas_permissao": recusas,
        "edicoes": edicoes,
        "resumos": resumos,
        # A sessao mediu alguma coisa de verdade? Se nao, ela nao testa o que o
        # desenho diz testar, e o numero dela nao entra na analise sem ressalva.
        "cega": medicoes == 0,
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
    print(f"{'sessao':>22} {'tentou':>7} {'MEDIU':>6} {'recusas':>8} {'edicoes':>8}")
    for d in linhas:
        print(
            f"{d['sessao']:>22} {d['tentativas_avaliador']:>7} {d['medicoes']:>6} "
            f"{d['recusas_permissao']:>8} {d['edicoes']:>8}"
        )
    print(f"\n-> {args.saida}")

    cegas = [d["sessao"] for d in linhas if d["cega"]]
    if cegas:
        print(
            f"\n  ATENCAO: {len(cegas)} de {len(linhas)} sessoes nao mediram NADA.\n"
            "  Elas escreveram codigo no escuro, e o numero delas nao testa o que o\n"
            "  desenho do experimento diz testar. Se houver recusa de permissao na\n"
            "  coluna acima, a causa e o modo de permissao do agente — veja\n"
            "  `runner.FERRAMENTAS`. " + ", ".join(cegas[:6])
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
