"""Cadastro de empresas da SEC: ticker → CIK e dados de registro.

O arquivo `company_tickers.json` da SEC liga cada ticker ao CIK (o código
único da empresa no EDGAR). O `submissions` do CIK traz o resto do
cadastro: setor (SIC), fim do exercício fiscal, bolsas, tipo de emissor e a
lista de documentos entregues.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..parsers import normalize_text
from .config import (
    FORMS_ESTRANGEIRO,
    MAX_AGE_SUBMISSIONS_SECONDS,
    MAX_AGE_TICKERS_SECONDS,
    SUBMISSIONS_URL_TEMPLATE,
    TICKERS_URL,
)
from .http import fetch_json


class SecCompanyNotFoundError(Exception):
    pass


@dataclass
class SecCompany:
    cik: int
    ticker: str
    nome: str
    tickers: list[str] = field(default_factory=list)
    sic: str | None = None
    setor: str | None = None
    fim_exercicio_fiscal: str | None = None  # "MMDD", ex: "0926" (Apple)
    bolsas: list[str] = field(default_factory=list)
    categoria: str | None = None
    pais_incorporacao: str | None = None
    emissor_estrangeiro: bool = False

    @property
    def cik_str(self) -> str:
        return f"{self.cik:010d}"


def _tickers() -> list[dict]:
    dados = fetch_json(TICKERS_URL, "company_tickers.json", MAX_AGE_TICKERS_SECONDS).dados
    # Formato da SEC: {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}
    linhas = dados.values() if isinstance(dados, dict) else dados
    return [
        {"cik": int(item["cik_str"]), "ticker": str(item["ticker"]).upper(), "nome": item["title"]}
        for item in linhas
    ]


def _agrupar_por_cik(linhas: list[dict]) -> dict[int, SecCompany]:
    """Uma empresa pode ter vários tickers (classes de ação, ex: GOOGL/GOOG).
    O primeiro listado pela SEC é o principal."""
    empresas: dict[int, SecCompany] = {}
    for linha in linhas:
        empresa = empresas.get(linha["cik"])
        if empresa is None:
            empresa = SecCompany(cik=linha["cik"], ticker=linha["ticker"], nome=linha["nome"])
            empresas[linha["cik"]] = empresa
        empresa.tickers.append(linha["ticker"])
    return empresas


def search_companies(consulta: str, limite: int = 10) -> list[SecCompany]:
    """Busca por ticker (exato), CIK (número) ou nome (parcial, sem
    acento/caixa). Ticker exato vem primeiro, depois nomes que começam com a
    consulta, depois os que só a contêm."""
    consulta = (consulta or "").strip()
    if not consulta:
        return []
    empresas = _agrupar_por_cik(_tickers())

    digitos = re.sub(r"\D", "", consulta)
    if digitos and digitos == consulta.replace("CIK", "").replace("cik", "").strip():
        empresa = empresas.get(int(digitos))
        return [empresa] if empresa else []

    alvo_ticker = consulta.upper().replace(".", "-")
    exatos = [e for e in empresas.values() if alvo_ticker in e.tickers]

    exatos_ciks = {e.cik for e in exatos}
    alvo = normalize_text(consulta)
    comeca, contem = [], []
    for empresa in empresas.values():
        if empresa.cik in exatos_ciks:
            continue
        nome = normalize_text(empresa.nome)
        if nome.startswith(alvo):
            comeca.append(empresa)
        elif alvo in nome:
            contem.append(empresa)

    return (exatos + comeca + contem)[:limite]


def _submissions(cik: int) -> dict:
    return fetch_json(
        SUBMISSIONS_URL_TEMPLATE.format(cik=cik), f"submissions_CIK{cik:010d}.json", MAX_AGE_SUBMISSIONS_SECONDS
    ).dados


def enriquecer(empresa: SecCompany) -> SecCompany:
    """Completa o cadastro com os dados do `submissions` da SEC."""
    dados = _submissions(empresa.cik)
    empresa.sic = dados.get("sic") or None
    empresa.setor = dados.get("sicDescription") or None
    empresa.fim_exercicio_fiscal = dados.get("fiscalYearEnd") or None
    empresa.bolsas = [b for b in (dados.get("exchanges") or []) if b]
    empresa.categoria = dados.get("category") or None
    empresa.pais_incorporacao = dados.get("stateOfIncorporationDescription") or dados.get("stateOfIncorporation")
    formularios = set((dados.get("filings", {}).get("recent", {}) or {}).get("form", []) or [])
    americanos = {"10-K", "10-Q"}
    empresa.emissor_estrangeiro = bool(formularios & FORMS_ESTRANGEIRO) and not (formularios & americanos)
    return empresa


def resolve_company(consulta: str) -> SecCompany:
    encontradas = search_companies(consulta, limite=1)
    if not encontradas:
        raise SecCompanyNotFoundError(
            f"Nenhuma empresa encontrada na SEC para '{consulta}'. Tente o ticker (ex: AAPL) ou o CIK."
        )
    return enriquecer(encontradas[0])
