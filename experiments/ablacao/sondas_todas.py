"""Roda a sonda de §3e nos cinco alvos e reescreve as declarações medidas.

As frações declaradas em `lab.sonda_100s_fracao` foram medidas com agentes que
não conseguiam executar o avaliador (a falha 8 do README). Uma sonda cega mede
"o que o agente escreve de cabeça em 100s", que é uma coisa diferente e
provavelmente menor. Estes números precisam ser refeitos com o conserto.

Sequencial, um alvo por vez, ~3 min e ~US$ 0,50 cada.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
ALVOS = ["sql_agg", "csv_normalize", "dedupe_match", "etl_agg", "sessionize"]


def roda(alvo: str) -> float | None:
    saida = subprocess.run(
        [sys.executable, str(Path(__file__).parent / "sonda.py"), "--alvo", alvo],
        cwd=str(RAIZ),
        capture_output=True,
        text=True,
        check=False,
        timeout=1800,
    )
    texto = saida.stdout + saida.stderr
    print(f"=== {alvo} ===\n{texto.strip()[-700:]}\n", flush=True)
    m = re.search(r"fracao do headroom\s+(-?\d+)%", texto)
    return int(m.group(1)) / 100.0 if m else None


def declara(alvo: str, fracao: float) -> None:
    caminho = RAIZ / "targets" / alvo / "target.yaml"
    s = caminho.read_text(encoding="utf-8")
    novo = f"  sonda_100s_fracao: {fracao:.2f}"
    if "sonda_100s_fracao:" in s:
        s = re.sub(r"^  sonda_100s_fracao: .*$", novo, s, count=1, flags=re.M)
    else:
        s = re.sub(r"^(lab:\n)", r"\1" + novo + "\n", s, count=1, flags=re.M)
    caminho.write_text(s, encoding="utf-8")


def main() -> int:
    medidas: dict[str, float] = {}
    for alvo in ALVOS:
        fracao = roda(alvo)
        if fracao is None:
            print(f"  {alvo}: sonda nao devolveu fracao; declaracao mantida", flush=True)
            continue
        medidas[alvo] = fracao
        declara(alvo, fracao)
        subprocess.run(
            ["git", "add", f"targets/{alvo}/target.yaml"],
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
                f"sonda §3e re-medida com o agente enxergando: {alvo} = {fracao:.0%}",
            ],
            cwd=str(RAIZ),
            check=False,
            capture_output=True,
        )
    (Path(__file__).parent / "resultados" / "sondas_vendo.json").write_text(
        json.dumps(medidas, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(medidas, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
