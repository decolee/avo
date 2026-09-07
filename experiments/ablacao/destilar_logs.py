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
import re
from pathlib import Path

AQUI = Path(__file__).resolve().parent


_RECUSA = ("requires approval", "requires permission", "permission to use", "denied")

# ---------------------------------------------------------------- o detector
#
# A versao original decidia as duas coisas por substring no texto:
#   TENTOU medir  <- o comando contem "avo-eval" ou "eval.py"
#   MEDIU         <- o resultado contem "avo_result" ou "medianas:"
#
# As duas estavam erradas, em direcoes opostas, e o erro so apareceu quando a
# ablacao do `sql_workload` reprovou 7 de 160 sessoes-passo (dessas, 6 tinham
# medido). Contado sobre 300 transcricoes daquele experimento:
#
#   * TENTOU: 1293 comandos casavam, dos quais 254 eram `cat`, 227 `sed`,
#     126 `grep` e 70 `ls`. LER o fonte do avaliador contava como tentar medir.
#   * MEDIU: um agente que canaliza a saida para um parser
#     (`./avo-eval | python3 -c "import json..."`) ou que importa `medir()` do
#     proprio `eval.py` para montar comparacao pareada nao emite nenhuma das
#     duas strings. 757 comandos tinham saida com cara de medicao e nao eram
#     reconhecidos.
#
# O detector marcava como cega exatamente a sessao que mede MELHOR — a que
# desconfia do ruido e faz medicao pareada, que e o que `kb/20-medicao.md`
# manda fazer.
#
# O conserto NAO e alargar as strings. E separar as duas perguntas e responder
# cada uma pelo sinal certo:
#
#   1. o comando EXECUTA alguma coisa, ou so LE arquivo?  -> posicao de comando
#   2. o que voltou tem forma de medicao?                 -> forma do resultado
#
# Nenhum dos dois sozinho serve. Aceitar (2) sozinho da 16,9% de falso positivo,
# porque `cat NOTES.md` e `cat kb/20-medicao.md` estao cheios de "primary = 1.16"
# e "quente=8.4" em prosa. E a conjuncao que fecha.

#: Corpo de heredoc nao e comando: e texto que o agente esta ESCREVENDO (quase
#: sempre no `NOTES.md`, onde ele cita `./avo-eval` em portugues). Sai antes de
#: qualquer analise de posicao, senao escrever sobre medir vira medir.
_HEREDOC = re.compile(r"<<-?\s*'?\"?(\w+)'?\"?.*?^\1\s*$", re.S | re.M)

#: Separadores de comando. Grosseiro de proposito: nao e um parser de shell, e
#: um particionador que erra para o lado seguro (mais segmentos, cada um
#: julgado por si).
_SEP = re.compile(r"\n|;|&&|\|\||\|")

#: O que vem ANTES do executavel sem mudar quem ele e: `cd x && `, `VAR=y `,
#: `time `, `exec `. Removido para que o primeiro token seja o programa.
_PREFIXO = re.compile(r"^(?:\w+=\S*\s+|cd\s+\S+\s+|exec\s+|time\s+|env\s+\S+=\S*\s+|sudo\s+)+")

#: Programas que LEEM arquivo. Um comando feito so destes nao mediu nada, nao
#: importa o que apareca na saida.
_LEITOR = re.compile(
    r"^(sed|grep|rg|cat|head|tail|less|wc|awk|ls|find|cp|mv|diff|git|echo|printf"
    r"|chmod|mkdir|test|\[)\b"
)

#: Programas que EXECUTAM o avaliador. O `python3` so conta quando o mesmo
#: segmento nomeia o avaliador — senao `python3 analise.py` viraria medicao.
_EXECUTA = re.compile(
    r"^(?:\./avo-eval\b"
    r"|(?:\S*/)?python3?\b(?=[^\n]*(?:eval\.py|avo\.cli\s+eval|avo-eval))"
    r"|(?:\S*/)?avo\b\s+eval\b"
    r"|\S*eval\.py\b)"
)

#: O avaliador e qualquer harness construido sobre ele imprimem numero com
#: nome. Cobre o formato padrao (`AVO_RESULT:`, `medianas:`), o parseado
#: (`primary=8.49`, `correct: ok`) e o por regime (`frio=2.4`, `'quente': 8.7`).
#: Os nomes de regime sao os dos seis alvos do repositorio.
_FORMA_DE_MEDICAO = re.compile(
    r"(avo_result"
    r"|medianas:"
    r"|primary\s*[=~:]\s*[0-9]"
    r"|correct\s*[:=]\s*(ok|true|false)"
    r"|(frio|quente|estreito|narrow|wide|skew|larga|curto|denso|longo)\s*=\s*[0-9]"
    r"|['\"](frio|quente|estreito|narrow|wide|skew|larga|curto|denso|longo)['\"]:\s*[0-9])",
    re.I,
)

#: Menciona a maquinaria de medicao do alvo — usado so para contar TENTATIVAS,
#: nunca para creditar uma medicao.
_MENCIONA = re.compile(r"(avo-eval|eval\.py|\bmedir\(|spec_from_file_location)", re.I)


def _segmentos(cmd: str) -> list[str]:
    """Quebra o comando em segmentos executaveis, sem os corpos de heredoc."""
    limpo = _HEREDOC.sub(" ", cmd)
    saida = []
    for seg in _SEP.split(limpo):
        seg = _PREFIXO.sub("", seg.strip()).strip()
        if seg:
            saida.append(seg)
    return saida


def executa_avaliador(cmd: str) -> bool:
    """O comando RODA o avaliador (em vez de ler o fonte dele)?"""
    return any(_EXECUTA.match(seg) for seg in _segmentos(cmd) if not _LEITOR.match(seg))


def so_le_arquivo(cmd: str) -> bool:
    """Todo segmento e um leitor de arquivo? Entao nada foi executado."""
    segs = _segmentos(cmd)
    return bool(segs) and all(_LEITOR.match(s) for s in segs)


def tentou_medir(cmd: str) -> bool:
    """Tentativa: rodou o avaliador, ou rodou algo que fala com a maquinaria."""
    return executa_avaliador(cmd) or (not so_le_arquivo(cmd) and bool(_MENCIONA.search(cmd)))


def mediu(cmd: str, resultado: str) -> bool:
    """Mediu de fato: nao foi so leitura, e o que voltou tem forma de medicao.

    Duas portas, porque ha dois caminhos legitimos e o detector antigo so
    conhecia meio do primeiro:

    * rodou o arbitro e ele voltou — `./avo-eval`, `python3 eval.py`;
    * rodou harness proprio sobre `medir()` e ele imprimiu numero com nome.

    A segunda porta exige `not so_le_arquivo` porque `cat NOTES.md` devolve
    "primary = 1.16" em prosa e nao mediu coisa nenhuma.
    """
    if so_le_arquivo(cmd):
        return False
    return executa_avaliador(cmd) or bool(_FORMA_DE_MEDICAO.search(resultado))


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
                    # O comando CRU, nao o `json.dumps` do input: as regexes de
                    # posicao dependem de quebra de linha de verdade, e o dump
                    # escapa `\n` em dois caracteres — o heredoc deixaria de ser
                    # reconhecido e o corpo dele voltaria a contar como comando.
                    cmd = str(((parte.get("input") or {}).get("command")) or "")
                    if nome == "Bash" and tentou_medir(cmd):
                        tentativas += 1
                        pendentes[str(parte.get("id"))] = cmd
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
                cmd = pendentes.pop(str(parte.get("tool_use_id")), None)
                if cmd is None:
                    continue  # resultado de outra ferramenta; nao diz nada sobre medicao
                corpo = json.dumps(parte.get("content") or "", ensure_ascii=False)
                if parte.get("is_error") or any(x in corpo.lower() for x in _RECUSA):
                    recusas += 1
                elif mediu(cmd, corpo):
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


#: Onde as transcricoes de cada braco vivem. Sao dois lugares porque sao dois
#: caminhos de codigo: o `greedy` e spawnado por este repositorio e escreve em
#: `logs/<braco>-s<n>.jsonl`; o `full` e spawnado pelo harness, que escreve um
#: arquivo por passo em `<run_dir>/logs/step-NNNN.log`. Um auditor que olhasse so
#: o primeiro daria o `full` como verificado sem ter olhado para ele.
_PADROES = ("logs/*.jsonl", "runs/*/*/logs/step-*.log")


def varre_experimento(raiz: Path) -> list[dict]:
    """Destila TODAS as transcricoes de um diretorio de experimento."""
    saida = []
    for padrao in _PADROES:
        for caminho in sorted(raiz.glob(padrao)):
            d = destila(caminho)
            if padrao.startswith("runs/"):
                # `step-0003` sozinho nao identifica nada; o run dir identifica.
                d["sessao"] = f"{caminho.parents[2].name}/{caminho.stem}"
            saida.append(d)
    return saida


def exige_visao(raiz: Path) -> tuple[bool, str]:
    """Portao: nenhuma sessao pode ter terminado sem medir.

    Chamado pela analise ANTES de qualquer estatistica. Uma sessao cega nao e
    ruido a mais na amostra — e uma sessao que nao testa o que o desenho diz
    testar, e a media dela contamina o braco inteiro. Foi assim que dois
    experimentos e US$ 343 produziram numeros que pareciam resultado.
    """
    linhas = varre_experimento(raiz)
    if not linhas:
        return False, f"nenhuma transcricao encontrada em {raiz}"
    cegas = [d for d in linhas if d["cega"]]
    if cegas:
        nomes = ", ".join(d["sessao"] for d in cegas[:8])
        return False, (
            f"{len(cegas)} de {len(linhas)} sessoes terminaram sem medir NADA: {nomes}"
            + ("..." if len(cegas) > 8 else "")
            + ". Veja `runner.FERRAMENTAS` e ABLATION_PROTOCOL.md §4."
        )
    return True, f"{len(linhas)} sessoes, todas com pelo menos uma medicao bem-sucedida"


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
