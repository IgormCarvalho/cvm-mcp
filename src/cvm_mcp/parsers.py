"""Leitura dos CSVs publicados pela CVM (encoding/separador fixos) e
utilitários de normalização de identificadores de empresa."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pandas as pd

from .config import CVM_CSV_ENCODING, CVM_CSV_SEP


def read_cvm_csv(path: Path, columns: list[str] | None = None) -> pd.DataFrame:
    # VL_CONTA já vem com "." como separador decimal (ex: "265438605.0000000000"),
    # então usamos o padrão do pandas em vez do decimal brasileiro (",").
    return pd.read_csv(
        path,
        sep=CVM_CSV_SEP,
        encoding=CVM_CSV_ENCODING,
        dtype={"CD_CVM": str, "CD_CONTA": str},
        usecols=columns,
        low_memory=False,
    )


def normalize_cnpj(value: str) -> str:
    """Remove tudo que não for dígito, mantendo o CNPJ comparável entre o
    que o usuário digita e o que vem nos CSVs (com pontuação)."""
    return re.sub(r"\D", "", value or "")


def normalize_text(value) -> str:
    if not isinstance(value, str):
        return ""
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return text.strip().lower()
