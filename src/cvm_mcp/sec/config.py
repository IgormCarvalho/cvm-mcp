"""Constantes da fonte SEC/EDGAR.

A SEC exige que todo acesso automatizado se identifique no cabeçalho
User-Agent com um nome e um e-mail de contato
(https://www.sec.gov/os/accessing-edgar-data). Esse valor é pessoal, por
isso vem SEMPRE de variável de ambiente e nunca fica no código.
"""

from __future__ import annotations

import os

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL_TEMPLATE = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
COMPANYFACTS_URL_TEMPLATE = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

USER_AGENT_ENV = "SEC_MCP_USER_AGENT"

# A SEC limita a 10 requisições por segundo por cliente. Ficamos abaixo com
# folga para nunca tomar bloqueio temporário de IP.
MAX_REQUESTS_PER_SECOND = 8

# Quanto tempo um arquivo em cache é usado sem nem consultar a SEC. Depois
# disso, a revalidação é condicional (ETag/Last-Modified), então um arquivo
# que não mudou não é baixado de novo.
MAX_AGE_TICKERS_SECONDS = 24 * 3600
MAX_AGE_SUBMISSIONS_SECONDS = 6 * 3600
MAX_AGE_COMPANYFACTS_SECONDS = 6 * 3600

HTTP_TIMEOUT_SECONDS = 60.0
HTTP_MAX_RETRIES = 3

# Formulários aceitos como fonte de demonstrações. 10-K/10-Q são de emissores
# americanos; 20-F e 40-F de emissores estrangeiros (anuais). Emendas (/A)
# entram porque costumam ser reapresentações.
FORMS_ANUAIS = frozenset({"10-K", "10-K/A", "10-KT", "10-KT/A", "20-F", "20-F/A", "40-F", "40-F/A"})
FORMS_TRIMESTRAIS = frozenset({"10-Q", "10-Q/A", "6-K", "6-K/A"})
FORMS_ACEITOS = FORMS_ANUAIS | FORMS_TRIMESTRAIS
FORMS_ESTRANGEIRO = frozenset({"20-F", "20-F/A", "40-F", "40-F/A", "6-K", "6-K/A"})


class UserAgentNotConfiguredError(RuntimeError):
    pass


def user_agent() -> str:
    """User-Agent exigido pela SEC, lido de SEC_MCP_USER_AGENT.

    Formato esperado: "Nome Sobrenome email@dominio.com" (ou nome da
    aplicação + e-mail). Sem um e-mail a SEC responde 403.
    """
    valor = os.environ.get(USER_AGENT_ENV, "").strip()
    if not valor or "@" not in valor:
        raise UserAgentNotConfiguredError(
            f"A SEC exige identificação. Defina a variável de ambiente {USER_AGENT_ENV} "
            'com seu nome e e-mail de contato, por exemplo: "Seu Nome seu@email.com". '
            "No Claude Desktop isso vai no bloco \"env\" do servidor em claude_desktop_config.json."
        )
    return valor
