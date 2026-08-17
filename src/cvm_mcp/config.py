"""Configuração e constantes do servidor. Caminhos resolvidos via platformdirs
para funcionar de forma idêntica em Windows, macOS e Linux sem hardcode."""

from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_cache_dir

APP_NAME = "cvm-mcp"

BASE_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA"
CAD_URL = f"{BASE_URL}/CAD/DADOS/cad_cia_aberta.csv"
DFP_URL_TEMPLATE = f"{BASE_URL}/DOC/DFP/DADOS/dfp_cia_aberta_{{ano}}.zip"
ITR_URL_TEMPLATE = f"{BASE_URL}/DOC/ITR/DADOS/itr_cia_aberta_{{ano}}.zip"

# Encoding e separador usados pela CVM em todos os CSVs publicados.
CVM_CSV_ENCODING = "latin-1"
CVM_CSV_SEP = ";"

# Primeiro ano com dados no padrão atual do portal de dados abertos.
DFP_FIRST_YEAR = 2010
# Limite inferior da varredura para trás ao montar a janela de trimestres.
ITR_FIRST_YEAR = 2011

# Quantos trimestres a análise padrão devolve (12 meses).
TRIMESTRES_PADRAO = 4

HTTP_TIMEOUT_SECONDS = 60.0
HTTP_USER_AGENT = f"{APP_NAME}/0.1 (+https://dados.cvm.gov.br)"


def cache_dir() -> Path:
    """Diretório local de cache. Pode ser sobrescrito com a variável de
    ambiente CVM_MCP_CACHE_DIR (útil em CI ou instalações restritas)."""
    override = os.environ.get("CVM_MCP_CACHE_DIR")
    base = Path(override) if override else Path(user_cache_dir(APP_NAME))
    base.mkdir(parents=True, exist_ok=True)
    return base
