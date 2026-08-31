"""labkit — a biblioteca compartilhada dos targets do AVO Data Lab.

Cada target do laboratório é domínio puro: um seed `x_0`, uma knowledge base `K`
e uma função de score `f`. Tudo que é *mecânica* de avaliação — medir tempo sem
perseguir ruído, emitir o JSON que o harness lê, rodar mutantes contra o gate,
congelar dataset com checksum — vive aqui, escrito uma vez.

O objetivo não é abstrair o target. É garantir que as três falhas registradas em
`docs/PLANO_AVO_DATA_ENGINEERING.md` não possam se repetir por descuido:

  Falha 1  gate fraco        -> `Gate` + `MutantSuite`: nenhum target é válido
                                sem mutantes que o gate rejeita.
  Falha 2  custo de avaliação -> `measure` reporta o custo real e
                                `budget_report` falha alto quando o seed sai da
                                faixa saudável.
  Falha 3  dataset à deriva  -> `datakit` grava um lock com SHA256 por arquivo.
"""

from .contracts import CanonError, canon_hash, canon_hash_rows, compare_mappings, stdlib_only
from .datakit import DatasetSpec, dataset_lock_path, generate, verify_lock
from .evalkit import (
    AVO_RESULT,
    Gate,
    Measurement,
    MutantSuite,
    Regime,
    budget_report,
    emit,
    emit_baselines,
    emit_failure,
    emit_success,
    implausible_speed,
    load_module,
    measure,
    read_floor,
    standard_parser,
    unique_alias,
)

__all__ = [
    "AVO_RESULT",
    "CanonError",
    "DatasetSpec",
    "Gate",
    "Measurement",
    "MutantSuite",
    "Regime",
    "budget_report",
    "canon_hash",
    "canon_hash_rows",
    "compare_mappings",
    "dataset_lock_path",
    "emit",
    "emit_baselines",
    "emit_failure",
    "emit_success",
    "generate",
    "implausible_speed",
    "load_module",
    "measure",
    "read_floor",
    "standard_parser",
    "stdlib_only",
    "unique_alias",
    "verify_lock",
]

__version__ = "1.0.0"
