"""Datasets congelados: geração determinística + lock com checksum.

O plano chama os datasets de "congelados e determinísticos". Isso só é verdade
se alguém verificar. Um `random.Random(seed)` é estável entre versões do CPython,
mas uma edição descuidada no gerador não é — e ela move o score de todas as
versões do lineage de uma vez, silenciosamente, invalidando a comparação que é o
ponto inteiro do experimento.

`dataset.lock.json` é a defesa: SHA256 por arquivo, commitado no repositório,
conferido pelos testes e pelo CI. Os dados em si não vão para o git (dezenas de
MB gerados em ~1s); o checksum vai.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

LOCK_NAME = "dataset.lock.json"


def sha256_file(path: str | Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


@dataclass
class DatasetSpec:
    """Um arquivo de dados gerado: nome, construtor e o porquê de existir."""

    filename: str
    build: Callable[[Path], None]
    purpose: str = ""
    rows: int | None = None


def dataset_lock_path(target_dir: str | Path) -> Path:
    return Path(target_dir) / LOCK_NAME


def data_dir(target_dir: str | Path) -> Path:
    return Path(target_dir) / "data"


@dataclass
class GenerateReport:
    written: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    lock_written: bool = False

    def render(self) -> str:
        parts = []
        if self.written:
            parts.append("gerados: " + ", ".join(self.written))
        if self.skipped:
            parts.append("já existiam: " + ", ".join(self.skipped))
        if self.lock_written:
            parts.append(f"{LOCK_NAME} atualizado")
        return "; ".join(parts) or "nada a fazer"


def generate(
    target_dir: str | Path,
    specs: list[DatasetSpec],
    force: bool = False,
    write_lock: bool = True,
) -> GenerateReport:
    """Gera os datasets do target de forma idempotente e grava o lock.

    Idempotente de propósito: `make setup` roda a cada sessão e regerar 20 MB
    toda vez é desperdício. `force=True` reconstrói do zero.
    """
    target_dir = Path(target_dir)
    out = data_dir(target_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = GenerateReport()

    for spec in specs:
        path = out / spec.filename
        if path.exists() and not force:
            report.skipped.append(spec.filename)
            continue
        tmp = path.with_suffix(path.suffix + ".partial")
        try:
            spec.build(tmp)
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                tmp.unlink()
        report.written.append(spec.filename)

    if write_lock:
        lock = {
            "version": 1,
            "files": {
                spec.filename: {
                    "sha256": sha256_file(out / spec.filename),
                    "bytes": (out / spec.filename).stat().st_size,
                    "purpose": spec.purpose,
                    **({"rows": spec.rows} if spec.rows is not None else {}),
                }
                for spec in specs
            },
        }
        existing = _read_lock(target_dir)
        if existing != lock:
            dataset_lock_path(target_dir).write_text(
                json.dumps(lock, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            report.lock_written = True
    return report


def _read_lock(target_dir: str | Path) -> dict | None:
    path = dataset_lock_path(target_dir)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def verify_lock(target_dir: str | Path) -> tuple[bool, str]:
    """Confere os dados presentes contra `dataset.lock.json`.

    Devolve `(ok, detalhe)`. Um dataset ausente e um dataset alterado são erros
    diferentes, e a mensagem diz qual é qual — a primeira se resolve com
    `make data`, a segunda é um bug no gerador.
    """
    target_dir = Path(target_dir)
    lock = _read_lock(target_dir)
    if lock is None:
        return False, f"{LOCK_NAME} ausente ou ilegível em {target_dir}"

    out = data_dir(target_dir)
    problems: list[str] = []
    for name, meta in sorted((lock.get("files") or {}).items()):
        path = out / name
        if not path.is_file():
            problems.append(f"{name}: ausente (rode `make data`)")
            continue
        actual = sha256_file(path)
        if actual != meta.get("sha256"):
            problems.append(
                f"{name}: checksum divergente (lock {str(meta.get('sha256'))[:12]}, "
                f"disco {actual[:12]}) — o gerador mudou?"
            )
    if problems:
        return False, "; ".join(problems)
    return True, f"{len(lock.get('files') or {})} arquivo(s) conferem com o lock"


def require(target_dir: str | Path, *filenames: str) -> list[Path]:
    """Resolve caminhos de dados, falhando com instrução acionável se faltarem."""
    out = data_dir(target_dir)
    missing = [n for n in filenames if not (out / n).is_file()]
    if missing:
        raise FileNotFoundError(
            "dataset ausente: "
            + ", ".join(missing)
            + f" em {out}. Rode `make data` (ou `python3 {Path(target_dir).name}/make_data.py`)."
        )
    return [out / n for n in filenames]
