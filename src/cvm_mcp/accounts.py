"""Mapeamento do plano de contas referencial da CVM para os itens usados nos
indicadores. A CVM padroniza a maioria dos códigos (ex: 3.01 = Receita) desde
2010, mas alguns itens (dívida, depreciação) variam de empresa para empresa,
então usamos busca por código com fallback em descrição normalizada.

Todo valor obtido por aqui é, por definição, uma aproximação a partir das
contas contábeis publicas — ver indicators.py para os avisos exibidos ao
usuário.
"""

from __future__ import annotations

import unicodedata

import pandas as pd

# --- Demonstração do Resultado (DRE) ---
DRE_RECEITA_LIQUIDA = "3.01"
DRE_EBIT = "3.05"  # Resultado Antes do Resultado Financeiro e dos Tributos
DRE_LUCRO_LIQUIDO_CODES = ("3.11", "3.09")
DRE_LUCRO_LIQUIDO_DESCRICOES = (
    "lucro/prejuizo consolidado do periodo",
    "lucro/prejuizo do periodo",
)

# --- Balanço Patrimonial Ativo (BPA) ---
BPA_ATIVO_CIRCULANTE = "1.01"
BPA_CAIXA_E_EQUIVALENTES = "1.01.01"

# --- Balanço Patrimonial Passivo (BPP) ---
BPP_PASSIVO_CIRCULANTE = "2.01"
BPP_PATRIMONIO_LIQUIDO = "2.03"

# Códigos padrão (plano de contas referencial da CVM) para empréstimos e
# financiamentos de curto e longo prazo. Usar o código exato evita somar
# duas vezes um item pai e seu próprio detalhamento (ex: 2.01.04 e
# 2.01.04.01 frequentemente têm o mesmo valor quando há só um sub-item).
DIVIDA_CP_CODE = "2.01.04"
DIVIDA_LP_CODE = "2.02.01"

DEPRECIACAO_PALAVRAS = ("deprecia", "amortiza")


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    return text.strip().lower()


def find_by_code(df: pd.DataFrame, code: str) -> float | None:
    rows = df.loc[df["CD_CONTA"] == code, "VL_CONTA"]
    if rows.empty:
        return None
    return float(rows.iloc[0])


def find_by_description(df: pd.DataFrame, *descriptions: str) -> float | None:
    normalized = df["DS_CONTA"].map(_normalize)
    for description in descriptions:
        target = _normalize(description)
        match = df.loc[normalized == target, "VL_CONTA"]
        if not match.empty:
            return float(match.iloc[0])
    return None


def sum_rows_containing(df: pd.DataFrame, *keywords: str, code_prefix: str | None = None) -> float | None:
    """Soma VL_CONTA de todas as linhas cuja descrição contenha qualquer uma
    das palavras-chave (busca usada para itens sem código padronizado, como
    depreciação/amortização ou dívida)."""
    subset = df
    if code_prefix is not None:
        subset = subset[subset["CD_CONTA"].str.startswith(code_prefix)]
    normalized = subset["DS_CONTA"].map(_normalize)
    mask = normalized.apply(lambda desc: any(keyword in desc for keyword in keywords))
    matches = subset.loc[mask, "VL_CONTA"]
    if matches.empty:
        return None
    return float(matches.sum())


def lucro_liquido(df: pd.DataFrame) -> float | None:
    for code in DRE_LUCRO_LIQUIDO_CODES:
        value = find_by_code(df, code)
        if value is not None:
            return value
    return find_by_description(df, *DRE_LUCRO_LIQUIDO_DESCRICOES)


def divida_bruta(bpp_df: pd.DataFrame) -> float | None:
    """Empréstimos e financiamentos (CP + LP). Usa sempre os códigos
    padrão (não soma por descrição) para não contar duas vezes um item pai
    e seu detalhamento. Retorna None se a empresa não usar esses códigos
    (nesse caso o indicador de dívida deve ser omitido, não estimado)."""
    curto_prazo = find_by_code(bpp_df, DIVIDA_CP_CODE)
    longo_prazo = find_by_code(bpp_df, DIVIDA_LP_CODE)
    if curto_prazo is None and longo_prazo is None:
        return None
    return (curto_prazo or 0.0) + (longo_prazo or 0.0)
