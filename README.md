# cvm-mcp

Servidor [MCP](https://modelcontextprotocol.io) que busca e trata dados
financeiros **direto do Portal de Dados Abertos da CVM**
(`dados.cvm.gov.br`), sem depender de terceiros. Expõe tools para um
cliente LLM (Claude Desktop, Claude Code, etc.) buscar empresas e calcular
indicadores a partir das demonstrações financeiras (DFP) publicadas.

## O que ele faz

| Tool | Quando usar |
|---|---|
| `buscar_empresa` | Resolver nome/CNPJ/código CVM antes de qualquer análise |
| `analisar_empresa` | Pedido genérico ("analise a empresa X") — últimos 5 anos, indicadores padrão |
| `obter_indicadores` | Pedido customizado de período (outro intervalo de anos, individual vs consolidado) |
| `obter_demonstrativo_bruto` | Pesquisa livre em uma conta contábil específica, sem cálculo |

Todos os valores monetários são normalizados para **R$ milhões**. Veja
[Limitações](#limitações-importantes) abaixo — a IA sempre recebe avisos
quando um dado não pôde ser obtido ou é uma estimativa.

## Instalação

Requer Python 3.10+. Funciona da mesma forma em Windows, macOS e Linux.

### Opção 1 — pipx (recomendado, isola o ambiente)

```bash
pipx install .
```

Roda em qualquer pasta depois, como o comando `cvm-mcp`.

### Opção 2 — pip em ambiente virtual

```bash
python -m venv .venv
# Windows (PowerShell)
.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate

pip install -e .
```

### Opção 3 — direto do código-fonte, sem instalar

```bash
pip install -r requirements.txt   # ou: pip install mcp[cli] httpx pandas platformdirs
python -m cvm_mcp
```

## Configurando no Claude Desktop

Edite `claude_desktop_config.json` (Windows:
`%APPDATA%\Claude\claude_desktop_config.json`; macOS:
`~/Library/Application Support/Claude/claude_desktop_config.json`) e
adicione:

```json
{
  "mcpServers": {
    "cvm": {
      "command": "cvm-mcp"
    }
  }
}
```

Se preferir não instalar com pipx (Opção 3), use:

```json
{
  "mcpServers": {
    "cvm": {
      "command": "python",
      "args": ["-m", "cvm_mcp"]
    }
  }
}
```

## Cache local

Os arquivos baixados da CVM (cadastro + ZIPs anuais de DFP) ficam em cache
local para não baixar de novo a cada consulta — a checagem usa
ETag/Last-Modified, então atualizações no portal da CVM são detectadas
automaticamente. Local padrão (via `platformdirs`, sem hardcode de SO):

- Windows: `%LOCALAPPDATA%\cvm-mcp`
- macOS: `~/Library/Caches/cvm-mcp`
- Linux: `~/.cache/cvm-mcp`

Para usar outro diretório (ex: ambientes restritos/CI), defina
`CVM_MCP_CACHE_DIR` antes de rodar o servidor.

## Limitações importantes

- **EBITDA é sempre uma estimativa** calculada a partir de EBIT (conta
  padrão da DRE) + Depreciação/Amortização extraída do fluxo de caixa —
  não é necessariamente igual ao "EBITDA ajustado" que a empresa divulga
  em release de resultados.
- **Sem dado de mercado**: a CVM não publica cotação, valor de mercado ou
  múltiplos (P/L, EV/EBITDA). Pedidos desse tipo ficam fora do escopo
  desta fonte.
- **Bancos, seguradoras e afins** usam um plano de contas de DRE diferente
  (não têm uma linha de "resultado antes do financeiro"), então
  EBIT/EBITDA estimado não é comparável ao de empresas não financeiras —
  o servidor sinaliza isso quando detecta o setor.
- **Dívida líquida** só é calculada quando a empresa usa os códigos
  contábeis padrão de Empréstimos e Financiamentos; quando não usa, o
  indicador é omitido (não estimado por aproximação).
- Nem toda empresa tem 5 anos de histórico (IPO recente, suspensão,
  cancelamento de registro) — anos sem dado vêm com aviso, não com zero.

## Desenvolvimento

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1   # ou source .venv/bin/activate
pip install -e .
python -m cvm_mcp            # roda o servidor via stdio
```

Estrutura do projeto:

```
src/cvm_mcp/
  config.py       # constantes e diretório de cache (cross-platform)
  cache.py        # download HTTP com cache condicional + extração de ZIP
  parsers.py      # leitura dos CSVs (encoding/separador da CVM)
  accounts.py     # mapa do plano de contas da CVM -> itens financeiros
  cvm_client.py   # busca de empresas e carregamento dos demonstrativos
  indicators.py   # cálculo dos indicadores a partir dos demonstrativos
  models.py       # estruturas de dados (Company, YearFinancials)
  server.py       # servidor MCP (FastMCP) e definição das tools
```
