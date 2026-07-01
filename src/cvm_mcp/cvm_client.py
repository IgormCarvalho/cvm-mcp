"""Camada de acesso aos dados abertos da CVM: cadastro de companhias e
demonstrações financeiras (DFP/ITR). Cuida de baixar, cachear, extrair e
filtrar os CSVs, devolvendo DataFrames já recortados para uma empresa/ano.
"""

from __future__ import annotations

from functools import lru_cache

import pandas as pd

from .cache import download_file, ensure_extracted
from .config import CAD_URL, DFP_URL_TEMPLATE, ITR_URL_TEMPLATE
from .models import Company
from .parsers import normalize_cnpj, normalize_text, read_cvm_csv

STATEMENTS = ("BPA", "BPP", "DRE", "DFC_MD", "DFC_MI", "DVA", "DMPL", "DRA")


class CompanyNotFoundError(Exception):
    pass


class StatementNotAvailableError(Exception):
    pass


@lru_cache(maxsize=1)
def load_cadastro() -> pd.DataFrame:
    path = download_file(CAD_URL)
    return read_cvm_csv(path)


def _company_from_row(row: pd.Series) -> Company:
    return Company(
        cnpj=row["CNPJ_CIA"],
        cd_cvm=str(row["CD_CVM"]),
        denom_social=row["DENOM_SOCIAL"],
        setor_ativ=row.get("SETOR_ATIV"),
        situacao_registro=row.get("SIT"),
        situacao_emissor=row.get("SIT_EMISSOR"),
    )


def search_companies(query: str, limit: int = 10) -> list[Company]:
    """Busca por nome (parcial, sem acento/caixa), CNPJ ou código CVM.
    Empresas ATIVAS aparecem antes de canceladas/suspensas no resultado."""
    cadastro = load_cadastro()
    digits = normalize_cnpj(query)

    if digits and len(digits) >= 6:
        by_cnpj = cadastro[cadastro["CNPJ_CIA"].map(normalize_cnpj).str.startswith(digits)]
        by_cd_cvm = cadastro[cadastro["CD_CVM"].astype(str).str.lstrip("0") == digits.lstrip("0")]
        matches = pd.concat([by_cnpj, by_cd_cvm])
    else:
        target = normalize_text(query)
        nome = cadastro["DENOM_SOCIAL"].map(normalize_text)
        comercial = cadastro["DENOM_COMERC"].map(normalize_text)
        matches = cadastro[nome.str.contains(target, na=False) | comercial.str.contains(target, na=False)]

    if matches.empty:
        return []

    # O cadastro da CVM tem uma linha por evento (ex: trocas de mercado/auditor),
    # então uma mesma empresa pode aparecer várias vezes com o mesmo CNPJ.
    matches = matches.drop_duplicates(subset=["CNPJ_CIA"])
    # SIT = situação do registro na CVM ("ATIVO"/"CANCELADA"/...); é esse campo,
    # não SIT_EMISSOR (que descreve a fase operacional), que sinaliza empresa ativa.
    matches = matches.assign(_ativo=(matches["SIT"].fillna("") == "ATIVO"))
    matches = matches.sort_values("_ativo", ascending=False)
    return [_company_from_row(row) for _, row in matches.head(limit).iterrows()]


def resolve_company(query: str) -> Company:
    matches = search_companies(query, limit=1)
    if not matches:
        raise CompanyNotFoundError(f"Nenhuma empresa encontrada para '{query}'.")
    return matches[0]


def _statement_filename(statement: str, ano: int, consolidado: bool, tipo: str) -> str:
    versao = "con" if consolidado else "ind"
    prefixo = "dfp" if tipo == "DFP" else "itr"
    return f"{prefixo}_cia_aberta_{statement}_{versao}_{ano}.csv"


def _zip_url(ano: int, tipo: str) -> str:
    template = DFP_URL_TEMPLATE if tipo == "DFP" else ITR_URL_TEMPLATE
    return template.format(ano=ano)


@lru_cache(maxsize=8)
def _ensure_year_extracted(ano: int, tipo: str) -> object:
    """Baixa e extrai o ZIP anual uma única vez por (ano, tipo) — todos os
    demonstrativos (DRE, BPA, BPP, ...) desse ano vêm do mesmo arquivo."""
    zip_path = download_file(_zip_url(ano, tipo), filename=f"{tipo.lower()}_cia_aberta_{ano}.zip")
    return ensure_extracted(zip_path)


@lru_cache(maxsize=128)
def load_statement(ano: int, statement: str, consolidado: bool = True, tipo: str = "DFP") -> pd.DataFrame:
    """Carrega um demonstrativo (ex: DRE) de TODAS as companhias para um
    ano, a partir do ZIP anual da CVM (baixado e extraído sob demanda).
    Cacheado em memória: dentro da mesma sessão do servidor, cada
    (ano, demonstrativo, versão) só é baixado/parseado uma vez."""
    if statement not in STATEMENTS:
        raise ValueError(f"Demonstrativo desconhecido: {statement}. Use um de {STATEMENTS}.")

    extract_dir = _ensure_year_extracted(ano, tipo)
    csv_path = extract_dir / _statement_filename(statement, ano, consolidado, tipo)
    if not csv_path.exists() and consolidado:
        # Nem toda empresa publica versão consolidada (ex: sem subsidiárias).
        csv_path = extract_dir / _statement_filename(statement, ano, False, tipo)
    if not csv_path.exists():
        raise StatementNotAvailableError(f"{statement} {tipo} {ano} não encontrado no pacote da CVM.")
    return read_cvm_csv(csv_path)


def company_statement(company: Company, ano: int, statement: str, consolidado: bool = True, tipo: str = "DFP") -> pd.DataFrame:
    """Mesmo que load_statement, mas já filtrado para uma empresa e para o
    exercício "ÚLTIMO" (o mais recente publicado naquele arquivo do ano),
    evitando duplicar a linha comparativa do ano anterior (PENÚLTIMO)."""
    full = load_statement(ano, statement, consolidado=consolidado, tipo=tipo)
    filtered = full[(full["CNPJ_CIA"] == company.cnpj) & (full["ORDEM_EXERC"] == "ÚLTIMO")]
    return filtered.reset_index(drop=True)


def company_statement_with_fallback(
    company: Company, ano: int, statement: str, consolidado: bool = True, tipo: str = "DFP"
) -> tuple[pd.DataFrame, bool]:
    """Tenta consolidado e cai para individual quando a empresa não tem
    linhas nesse ano/versão (comum em companhias sem subsidiárias).
    Retorna (dados, usou_consolidado)."""
    df = company_statement(company, ano, statement, consolidado=consolidado, tipo=tipo)
    if not df.empty or not consolidado:
        return df, consolidado
    df = company_statement(company, ano, statement, consolidado=False, tipo=tipo)
    return df, False


def scale_to_millions(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza VL_CONTA para milhões de reais a partir de ESCALA_MOEDA
    (a CVM publica em MIL ou UNIDADE, nunca já em milhões)."""
    if df.empty:
        return df
    factor = df["ESCALA_MOEDA"].map({"MIL": 1_000.0, "UNIDADE": 1_000_000.0}).fillna(1_000_000.0)
    out = df.copy()
    out["VL_CONTA"] = out["VL_CONTA"] / factor
    return out
