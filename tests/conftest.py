"""Fixtures dos testes da fonte SEC.

Os testes rodam 100% offline: `fetch_json` é substituído por um dicionário
URL → JSON com empresas sintéticas que reproduzem os formatos reais da SEC
(companyfacts, submissions e company_tickers):

- ACME (CIK 1): emissor americano, exercício = ano civil. DRE com trimestres
  isolados no 10-Q, fluxo de caixa só acumulado, 10-K anual, uma emenda
  10-K/A que reapresenta a receita de 2024.
- FRUTA (CIK 2): exercício fiscal terminando no fim de setembro (52/53
  semanas), como a Apple.
- NUEST (CIK 3): emissor estrangeiro, 20-F em IFRS, sem trimestres em XBRL.
"""

from __future__ import annotations

import pytest

from cvm_mcp.sec import facts as sec_facts
from cvm_mcp.sec import http as sec_http
from cvm_mcp.sec.http import Resposta


def _fato(start, end, val, form, filed, fy, fp, accn="0000000000-00-000000"):
    f = {"end": end, "val": val, "accn": accn, "fy": fy, "fp": fp, "form": form, "filed": filed}
    if start:
        f["start"] = start
    return f


def _acme() -> dict:
    receita_tri = {  # 2024 e 2025 por trimestre, 2026 até o 2T
        ("2024-01-01", "2024-03-31"): 100, ("2024-04-01", "2024-06-30"): 110,
        ("2024-07-01", "2024-09-30"): 120, ("2025-01-01", "2025-03-31"): 130,
        ("2025-04-01", "2025-06-30"): 140, ("2025-07-01", "2025-09-30"): 150,
        ("2026-01-01", "2026-03-31"): 160, ("2026-04-01", "2026-06-30"): 170,
    }
    m = 1_000_000
    receita = []
    for (s, e), v in receita_tri.items():
        fy = int(e[:4])
        receita.append(_fato(s, e, v * m, "10-Q", f"{e[:4]}-{int(e[5:7]) + 1:02d}-10", fy, "Q"))
    # Anual 2024: 10-K original (500) e emenda 10-K/A reapresentando para 505.
    receita.append(_fato("2024-01-01", "2024-12-31", 500 * m, "10-K", "2025-02-20", 2024, "FY", "acc-10k-2024"))
    receita.append(_fato("2024-01-01", "2024-12-31", 505 * m, "10-K/A", "2025-04-15", 2024, "FY", "acc-10ka-2024"))
    # O 10-K de 2025 repete 2024 como comparativo (com o valor reapresentado).
    receita.append(_fato("2024-01-01", "2024-12-31", 505 * m, "10-K", "2026-02-20", 2025, "FY", "acc-10k-2025"))
    receita.append(_fato("2025-01-01", "2025-12-31", 590 * m, "10-K", "2026-02-20", 2025, "FY", "acc-10k-2025"))

    lucro = [
        _fato("2025-01-01", "2025-03-31", 13 * m, "10-Q", "2025-05-01", 2025, "Q1"),
        _fato("2025-04-01", "2025-06-30", 14 * m, "10-Q", "2025-08-01", 2025, "Q2"),
        _fato("2025-07-01", "2025-09-30", 15 * m, "10-Q", "2025-11-01", 2025, "Q3"),
        _fato("2025-01-01", "2025-12-31", 60 * m, "10-K", "2026-02-20", 2025, "FY"),
        _fato("2026-01-01", "2026-03-31", 16 * m, "10-Q", "2026-05-01", 2026, "Q1"),
        _fato("2026-04-01", "2026-06-30", 17 * m, "10-Q", "2026-08-01", 2026, "Q2"),
    ]
    lpa = [
        _fato("2025-07-01", "2025-09-30", 0.15, "10-Q", "2025-11-01", 2025, "Q3"),
        _fato("2025-01-01", "2025-12-31", 0.60, "10-K", "2026-02-20", 2025, "FY"),
        _fato("2026-01-01", "2026-03-31", 0.16, "10-Q", "2026-05-01", 2026, "Q1"),
        _fato("2026-04-01", "2026-06-30", 0.17, "10-Q", "2026-08-01", 2026, "Q2"),
    ]
    # Fluxo de caixa: só acumulado no ano (3, 6, 9 meses e anual).
    fco = [
        _fato("2025-01-01", "2025-03-31", 20 * m, "10-Q", "2025-05-01", 2025, "Q1"),
        _fato("2025-01-01", "2025-06-30", 45 * m, "10-Q", "2025-08-01", 2025, "Q2"),
        _fato("2025-01-01", "2025-09-30", 75 * m, "10-Q", "2025-11-01", 2025, "Q3"),
        _fato("2025-01-01", "2025-12-31", 110 * m, "10-K", "2026-02-20", 2025, "FY"),
        _fato("2026-01-01", "2026-03-31", 30 * m, "10-Q", "2026-05-01", 2026, "Q1"),
        _fato("2026-01-01", "2026-06-30", 62 * m, "10-Q", "2026-08-01", 2026, "Q2"),
    ]
    ativos, passivo_pl = [], []
    for e, v in {"2025-09-30": 1000, "2025-12-31": 1050, "2026-03-31": 1100, "2026-06-30": 1150}.items():
        form = "10-K" if e.endswith("12-31") else "10-Q"
        ativos.append(_fato(None, e, v * m, form, "2026-08-01", 2026, "Q"))
        passivo_pl.append(_fato(None, e, v * m, form, "2026-08-01", 2026, "Q"))
    # Um fato de 8-K não pode entrar (formulário não aceito).
    ativos.append(_fato(None, "2026-07-15", 9999 * m, "8-K", "2026-07-20", 2026, "Q"))

    return {
        "cik": 1,
        "entityName": "ACME CORP",
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": receita}},
                "NetIncomeLoss": {"units": {"USD": lucro}},
                "EarningsPerShareDiluted": {"units": {"USD/shares": lpa}},
                "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": fco}},
                "Assets": {"units": {"USD": ativos}},
                "LiabilitiesAndStockholdersEquity": {"units": {"USD": passivo_pl}},
            }
        },
    }


def _fruta() -> dict:
    m = 1_000_000
    # FY2025: 2024-09-29 a 2025-09-27. Trimestres de 13 semanas.
    receita = [
        _fato("2024-09-29", "2024-12-28", 120 * m, "10-Q", "2025-01-31", 2025, "Q1"),
        _fato("2024-12-29", "2025-03-29", 95 * m, "10-Q", "2025-05-02", 2025, "Q2"),
        _fato("2025-03-30", "2025-06-28", 94 * m, "10-Q", "2025-08-01", 2025, "Q3"),
        _fato("2024-09-29", "2025-09-27", 416 * m, "10-K", "2025-10-31", 2025, "FY"),
        _fato("2025-09-28", "2025-12-27", 130 * m, "10-Q", "2026-01-30", 2026, "Q1"),
    ]
    return {"cik": 2, "entityName": "FRUTA INC", "facts": {"us-gaap": {
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": receita}},
    }}}


def _nuest() -> dict:
    m = 1_000_000
    receita = [
        _fato("2024-01-01", "2024-12-31", 11_500 * m, "20-F", "2025-04-10", 2024, "FY"),
        _fato("2025-01-01", "2025-12-31", 15_000 * m, "20-F", "2026-04-10", 2025, "FY"),
    ]
    lucro = [_fato("2025-01-01", "2025-12-31", 2_800 * m, "20-F", "2026-04-10", 2025, "FY")]
    ativos = [_fato(None, "2025-12-31", 60_000 * m, "20-F", "2026-04-10", 2025, "FY")]
    return {"cik": 3, "entityName": "NU ESTRANGEIRA LTD", "facts": {"ifrs-full": {
        "Revenue": {"units": {"USD": receita}},
        "ProfitLossAttributableToOwnersOfParent": {"units": {"USD": lucro}},
        "Assets": {"units": {"USD": ativos}},
    }}}


TICKERS = {
    "0": {"cik_str": 1, "ticker": "ACME", "title": "Acme Corp"},
    "1": {"cik_str": 2, "ticker": "FRUT", "title": "Fruta Inc"},
    "2": {"cik_str": 3, "ticker": "NUES", "title": "Nu Estrangeira Ltd"},
    "3": {"cik_str": 1, "ticker": "ACME-B", "title": "Acme Corp"},
}


def _submissions(cik, fye, forms, sic="7372", desc="Services-Prepackaged Software"):
    return {
        "cik": str(cik), "sic": sic, "sicDescription": desc, "fiscalYearEnd": fye,
        "exchanges": ["NYSE"], "category": "Large accelerated filer",
        "stateOfIncorporation": "DE", "filings": {"recent": {"form": forms}},
    }


RESPOSTAS = {
    "https://www.sec.gov/files/company_tickers.json": TICKERS,
    "https://data.sec.gov/submissions/CIK0000000001.json": _submissions(1, "1231", ["10-Q", "10-K", "8-K"]),
    "https://data.sec.gov/submissions/CIK0000000002.json": _submissions(2, "0927", ["10-Q", "10-K"]),
    "https://data.sec.gov/submissions/CIK0000000003.json": _submissions(3, "1231", ["20-F", "6-K"], "6199", "Finance Services"),
    "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json": _acme(),
    "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000002.json": _fruta(),
    "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000003.json": _nuest(),
}


@pytest.fixture(autouse=True)
def sec_offline(monkeypatch, tmp_path):
    monkeypatch.setenv("CVM_MCP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SEC_MCP_USER_AGENT", "Teste Automatizado teste@example.com")
    chamadas: list[str] = []

    def falso_fetch(url, filename, max_age_seconds):
        chamadas.append(url)
        return Resposta(RESPOSTAS[url])

    for modulo in ("cvm_mcp.sec.companies", "cvm_mcp.sec.facts"):
        monkeypatch.setattr(f"{modulo}.fetch_json", falso_fetch)
    sec_facts.limpar_cache_memoria()
    yield chamadas
    sec_facts.limpar_cache_memoria()


__all__ = ["sec_http"]
