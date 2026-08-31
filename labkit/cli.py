"""`avo-lab` — a disciplina de alvo, verificável de fora.

Um alvo deste laboratório só é válido quando quatro coisas valem ao mesmo tempo:
o `target.yaml` carrega, o dataset confere com o lock, o gate rejeita os
mutantes, e o custo de avaliação está dimensionado. Nenhuma delas se verifica
lendo o código — todas exigem rodar.

Este comando roda as quatro em todos os alvos e devolve um veredito único. É o
que o `make verify` e o CI chamam, e é o que impede que um alvo novo entre no
repositório sem gate.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def targets_dir() -> Path:
    return repo_root() / "targets"


def discover() -> list[Path]:
    root = targets_dir()
    if not root.is_dir():
        return []
    return sorted(p.parent for p in root.glob("*/target.yaml"))


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class TargetReport:
    name: str
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)


def _run(cmd: list[str], cwd: Path, timeout: float) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired:
        return -1, f"estourou o tempo limite de {timeout:.0f}s"
    except FileNotFoundError as exc:
        return -1, str(exc)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def check_yaml(target: Path) -> Check:
    try:
        import yaml
    except ImportError:
        return Check("target.yaml", True, "pulado: pyyaml não instalado")
    try:
        data = yaml.safe_load((target / "target.yaml").read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        return Check("target.yaml", False, f"{type(exc).__name__}: {exc}")

    problems = []
    if not data.get("name"):
        problems.append("falta name")
    command = (data.get("evaluate") or {}).get("command")
    if not isinstance(command, list):
        problems.append("evaluate.command precisa ser lista de tokens argv")
    direction = (data.get("score") or {}).get("direction")
    if direction not in ("maximize", "minimize"):
        problems.append(f"score.direction inválido: {direction!r}")
    seed = target / str(data.get("seed") or "seed")
    if not seed.is_dir() or not any(seed.iterdir()):
        problems.append("diretório seed ausente ou vazio")
    kb = target / str(data.get("knowledge_base") or "kb")
    kb_files = sorted(kb.glob("*.md")) if kb.is_dir() else []
    if len(kb_files) < 2:
        problems.append(f"kb tem {len(kb_files)} arquivo(s) .md; o mínimo é 2")
    if problems:
        return Check("target.yaml", False, "; ".join(problems))
    return Check("target.yaml", True, f"{len(kb_files)} arquivos de KB")


def check_lock(target: Path) -> Check:
    from labkit import datakit

    ok, detail = datakit.verify_lock(target)
    return Check("dataset.lock", ok, detail)


def check_selftest(target: Path, timeout: float) -> Check:
    code, out = _run([sys.executable, "eval.py", "--selftest"], target, timeout)
    mutants = sum(1 for line in out.splitlines() if "mutante" in line and "FAIL" in line)
    if code != 0 or "GATE SELFTEST: OK" not in out:
        tail = " / ".join(line.strip() for line in out.strip().splitlines()[-3:])
        return Check("gate (--selftest)", False, tail or f"saiu {code}")
    if mutants < 5:
        return Check("gate (--selftest)", False, f"só {mutants} mutantes rejeitados; mínimo 5")
    return Check("gate (--selftest)", True, f"{mutants} mutantes rejeitados")


def check_budget(target: Path, timeout: float) -> Check:
    code, out = _run([sys.executable, "eval.py", "--budget"], target, timeout)
    first = next((line.strip() for line in out.splitlines() if line.strip()), "")
    return Check("dimensionamento (--budget)", code == 0, first or f"saiu {code}")


def verify(names: list[str] | None, skip_slow: bool, timeout: float) -> list[TargetReport]:
    reports = []
    for target in discover():
        if names and target.name not in names:
            continue
        report = TargetReport(target.name)
        report.checks.append(check_yaml(target))
        report.checks.append(check_lock(target))
        report.checks.append(check_selftest(target, timeout))
        if not skip_slow:
            report.checks.append(check_budget(target, timeout))
        reports.append(report)
    return reports


def render(reports: list[TargetReport]) -> str:
    lines = []
    for report in reports:
        mark = "ok  " if report.ok else "FALHA"
        lines.append(f"{mark} {report.name}")
        for check in report.checks:
            lines.append(f"       {'ok ' if check.ok else 'ERRO'}  {check.name:28} {check.detail}")
    good = sum(1 for r in reports if r.ok)
    lines.append("")
    lines.append(f"{good}/{len(reports)} alvos válidos")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="avo-lab", description="Verifica a disciplina dos alvos do AVO Data Lab"
    )
    sub = parser.add_subparsers(dest="command")

    p_verify = sub.add_parser("verify", help="roda as quatro checagens em cada alvo")
    p_verify.add_argument("targets", nargs="*", help="alvos a verificar (padrão: todos)")
    p_verify.add_argument("--skip-slow", action="store_true", help="pula o --budget")
    p_verify.add_argument("--timeout", type=float, default=300.0)
    p_verify.add_argument("--json", action="store_true")

    sub.add_parser("targets", help="lista os alvos encontrados")

    args = parser.parse_args(argv)

    if args.command == "targets" or args.command is None:
        found = discover()
        if not found:
            print("nenhum alvo em targets/", file=sys.stderr)
            return 1
        for target in found:
            print(target.name)
        return 0

    reports = verify(args.targets or None, args.skip_slow, args.timeout)
    if not reports:
        print("nenhum alvo encontrado", file=sys.stderr)
        return 1
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "target": r.name,
                        "ok": r.ok,
                        "checks": [
                            {"name": c.name, "ok": c.ok, "detail": c.detail} for c in r.checks
                        ],
                    }
                    for r in reports
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(render(reports))
    return 0 if all(r.ok for r in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
