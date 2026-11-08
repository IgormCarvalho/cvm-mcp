"""Testes da fonte SEC — todos offline (ver conftest.py)."""

from __future__ import annotations

import pytest

from cvm_mcp import server
from cvm_mcp.sec import config as sec_config
from cvm_mcp.sec import http as sec_http


def _conta(periodo: dict, codigo: str) -> dict | None:
    return next((c for c in periodo["contas"] if c["codigo"] == codigo), None)


# --- busca de empresas -------------------------------------------------------

def test_busca_por_ticker_agrupa_classes():
    r = server.sec_buscar_empresa("acme")
    assert r["encontrado"]
    primeira = r["empresas"][0]
    assert primeira["ticker"] == "ACME"
    assert primeira["tickers"] == ["ACME", "ACME-B"]
    assert primeira["cik"] == "0000000001"
    assert len(r["empresas"]) == 1  # não duplica a empresa por ter duas classes


def test_busca_por_cik_e_por_nome():
    assert server.sec_buscar_empresa("0000000002")["empresas"][0]["ticker"] == "FRUT"
    assert server.sec_buscar_empresa("estrangeira")["empresas"][0]["ticker"] == "NUES"
    assert not server.sec_buscar_empresa("inexistente xyz")["encontrado"]


# --- visão trimestral --------------------------------------------------------

def test_analisar_empresa_ultimos_quatro_trimestres():
    r = server.sec_analisar_empresa("ACME")
    assert r["encontrado"]
    assert r["moeda"] == "USD"
    assert [p["trimestre"] for p in r["periodos"]] == ["3T25", "4T25", "1T26", "2T26"]
    receita = [_conta(p, "3.01")["valor"] for p in r["periodos"]]
    assert receita == [150.0, 170.0, 160.0, 170.0]
    assert r["empresa"]["fim_exercicio_fiscal"] == "1231"


def test_quarto_trimestre_derivado_e_marcado():
    r = server.sec_analisar_empresa("ACME")
    q4 = r["periodos"][1]
    assert q4["trimestre"] == "4T25" and q4["derivado"]
    lucro = _conta(q4, "3.13")
    assert lucro["valor"] == 18.0  # 60 (10-K) − 42 (soma 1T–3T)
    assert lucro["derivado"]
    assert "10-K" in lucro["formulario"]
    assert any("4º trimestre" in a for a in r["avisos"])


def test_lpa_nao_e_derivado_no_quarto_trimestre():
    r = server.sec_analisar_empresa("ACME")
    q3, q4 = r["periodos"][0], r["periodos"][1]
    assert _conta(q3, "3.99.02")["valor"] == 0.15
    assert _conta(q3, "3.99.02")["unidade"] == "por ação"
    assert _conta(q4, "3.99.02") is None


def test_fluxo_de_caixa_acumulado_vira_trimestre_isolado():
    r = server.sec_obter_demonstrativo_trimestral("ACME", "DFC", 6)
    valores = {p["trimestre"]: _conta(p, "6.01") for p in r["periodos"]}
    assert valores["1T25"]["valor"] == 20.0 and not valores["1T25"]["derivado"]
    assert valores["2T25"]["valor"] == 25.0 and valores["2T25"]["derivado"]
    assert valores["3T25"]["valor"] == 30.0
    assert valores["4T25"]["valor"] == 35.0
    assert valores["2T26"]["valor"] == 32.0
    assert any("acumuladas no ano" in a for a in r["avisos"])


def test_balanco_e_saldo_na_data_e_ignora_formulario_nao_aceito():
    r = server.sec_obter_demonstrativo_trimestral("ACME", "BPA", 4)
    assert r["tipo_conta"] == "estoque"
    fins = [p["fim"] for p in r["periodos"]]
    assert fins == ["2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30"]
    assert [_conta(p, "1")["valor"] for p in r["periodos"]] == [1000.0, 1050.0, 1100.0, 1150.0]
    assert not any(p["derivado"] for p in r["periodos"])
    assert all(_conta(p, "1")["valor"] != 9999.0 for p in r["periodos"])  # o 8-K ficou de fora


def test_reapresentacao_usa_entrega_mais_recente():
    r = server.sec_obter_demonstrativo_anual("ACME", 2024, "DRE")
    receita = _conta(r, "3.01")
    assert receita["valor"] == 505.0
    assert receita.get("reapresentado") is True
    assert any("reapresentado" in a for a in r["avisos"])


def test_contas_registram_origem():
    r = server.sec_analisar_empresa("ACME")
    receita = _conta(r["periodos"][0], "3.01")
    assert receita["tag_xbrl"] == "us-gaap:Revenues"
    assert receita["formulario"] == "10-Q"
    assert receita["arquivado_em"]


# --- exercício fiscal não-calendário ----------------------------------------

def test_exercicio_fiscal_em_setembro():
    r = server.sec_analisar_empresa("FRUT")
    rotulos = [(p["trimestre"], p["inicio"], p["fim"]) for p in r["periodos"]]
    assert rotulos[-1] == ("1T26", "2025-09-28", "2025-12-27")
    q4 = next(p for p in r["periodos"] if p["trimestre"] == "4T25")
    assert q4["inicio"] == "2025-06-29" and q4["fim"] == "2025-09-27"
    assert _conta(q4, "3.01")["valor"] == 107.0  # 416 − (120 + 95 + 94)
    assert _conta(q4, "3.01")["tag_xbrl"].endswith("RevenueFromContractWithCustomerExcludingAssessedTax")


def test_anual_usa_ano_fiscal_da_empresa():
    r = server.sec_obter_demonstrativo_anual("FRUT", 2025, "DRE")
    assert r["encontrado"] and r["inicio"] == "2024-09-29" and r["fim"] == "2025-09-27"
    assert _conta(r, "3.01")["valor"] == 416.0
    faltando = server.sec_obter_demonstrativo_anual("FRUT", 2019, "DRE")
    assert not faltando["encontrado"] and "2025" in faltando["aviso"]


# --- emissor estrangeiro (IFRS) ---------------------------------------------

def test_estrangeiro_sem_trimestres_avisa():
    r = server.sec_analisar_empresa("NUES")
    assert not r["encontrado"]
    assert r["empresa"]["emissor_estrangeiro"]
    assert any("6-K" in a for a in r["avisos"])


def test_estrangeiro_anual_em_ifrs():
    r = server.sec_obter_demonstrativo_anual("NUES", 2025, "DRE")
    assert r["encontrado"]
    assert _conta(r, "3.01")["valor"] == 15000.0
    assert _conta(r, "3.01")["tag_xbrl"] == "ifrs-full:Revenue"
    assert _conta(r, "3.13")["valor"] == 2800.0


# --- conta XBRL avulsa e erros ----------------------------------------------

def test_conta_xbrl_bruta():
    r = server.sec_obter_conta_xbrl("ACME", "NetCashProvidedByUsedInOperatingActivities")
    assert r["encontrado"]
    assert r["valores"][-1]["fim"] == "2026-06-30" and r["valores"][-1]["valor"] == 62.0
    r2 = server.sec_obter_conta_xbrl("ACME", "Revenue")
    assert not r2["encontrado"] and "Revenues" in r2["tags_parecidas"]


def test_demonstrativo_invalido():
    assert not server.sec_obter_demonstrativo_trimestral("ACME", "XYZ")["encontrado"]


def test_sem_user_agent_explica_como_configurar(monkeypatch):
    monkeypatch.delenv("SEC_MCP_USER_AGENT", raising=False)
    with pytest.raises(sec_config.UserAgentNotConfiguredError, match="SEC_MCP_USER_AGENT"):
        sec_config.user_agent()
    monkeypatch.setenv("SEC_MCP_USER_AGENT", "sem email")
    with pytest.raises(sec_config.UserAgentNotConfiguredError):
        sec_config.user_agent()


def test_http_respeita_limite_de_taxa(monkeypatch):
    import time

    momentos = []
    monkeypatch.setattr(sec_http, "_ultimo_request", 0.0)
    for _ in range(5):
        sec_http._throttle()
        momentos.append(time.monotonic())
    intervalos = [b - a for a, b in zip(momentos, momentos[1:])]
    assert min(intervalos) >= 1 / sec_config.MAX_REQUESTS_PER_SECOND - 0.005


def test_http_usa_cache_quando_sec_falha(monkeypatch, tmp_path):
    """Cache: dentro do max_age não consulta a SEC; se a SEC cair, usa a cópia."""
    import httpx

    url = "https://data.sec.gov/teste.json"
    chamadas = {"n": 0}

    def handler(request):
        chamadas["n"] += 1
        assert "teste@example.com" in request.headers["User-Agent"]
        if chamadas["n"] == 1:
            return httpx.Response(200, json={"ok": 1}, headers={"ETag": '"v1"'})
        return httpx.Response(503)

    transporte = httpx.MockTransport(handler)
    original = httpx.Client

    def cliente_falso(*args, **kwargs):
        kwargs["transport"] = transporte
        return original(*args, **kwargs)

    monkeypatch.setattr(sec_http.httpx, "Client", cliente_falso)
    monkeypatch.setattr(sec_http.time, "sleep", lambda s: None)

    assert sec_http.fetch_json(url, "teste.json", 3600).dados == {"ok": 1}
    assert sec_http.fetch_json(url, "teste.json", 3600).dados == {"ok": 1}
    assert chamadas["n"] == 1  # segunda leitura veio do cache, sem request

    resposta = sec_http.fetch_json(url, "teste.json", 0)  # força revalidar; SEC fora do ar
    assert resposta.dados == {"ok": 1} and resposta.stale
