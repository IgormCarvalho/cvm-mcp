# cvm-mcp

Servidor [MCP](https://modelcontextprotocol.io) que busca e trata dados
financeiros **direto do Portal de Dados Abertos da CVM**
(`dados.cvm.gov.br`), sem depender de terceiros. Expõe tools para um
cliente LLM (Claude Desktop, Claude Code, etc.) consultar as demonstrações
financeiras publicadas pelas companhias abertas.

A visão padrão é **trimestral**: as tools partem do último trimestre que a
empresa publicou e devolvem os **12 meses anteriores, trimestre a
trimestre**, com as contas contábeis como a CVM publica — sem indicadores
calculados.

## O que ele faz

| Tool | Quando usar |
|---|---|
| `buscar_empresa` | Resolver nome/CNPJ/código CVM antes de qualquer análise |
| `analisar_empresa` | Pedido genérico ("analise a empresa X") — DRE dos últimos 4 trimestres |
| `obter_demonstrativo_trimestral` | Outro demonstrativo (balanço, fluxo de caixa) ou mais de 4 trimestres |
| `obter_demonstrativo_anual` | Quando o usuário pedir explicitamente o exercício anual fechado (DFP) |

Todos os valores monetários são normalizados para **R$ milhões**. Veja
[Limitações](#limitações-importantes) abaixo — a IA sempre recebe avisos
quando um dado é derivado ou não pôde ser obtido.

## Como o trimestre é montado

O ITR da CVM publica **apenas 1T, 2T e 3T**, e já traz cada trimestre
isolado além dos acumulados do exercício — então recortar um trimestre é
filtrar período, não subtrair.

O **4T não existe no ITR**. Ele é derivado como `exercício completo (DFP) −
acumulado até o 3T (ITR)`, casado conta a conta pelo código contábil. Todo
período assim vem marcado com `derivado: true` na resposta, junto de um
aviso explícito.

Duas consequências que valem entender:

- **Contas de estoque nunca são derivadas.** BPA e BPP são saldos numa
  data, então o fechamento do exercício já é o valor do 4T. Só as contas de
  fluxo (DRE, DFC, DVA, DRA, DMPL) passam pela subtração.
- **O "último trimestre" é por empresa, não global.** Exercícios sociais
  não-calendário fecham em outros meses — a Camil, por exemplo, tem
  trimestres mar–mai, jun–ago, set–nov e dez–fev. O servidor resolve isso
  pelas datas de cada companhia, e o rótulo (`2T26`) sempre vem
  acompanhado de `inicio` e `fim`.

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

Os arquivos baixados da CVM (cadastro + ZIPs anuais de ITR e DFP) ficam em
cache local para não baixar de novo a cada consulta — a checagem usa
ETag/Last-Modified, então atualizações no portal da CVM são detectadas
automaticamente.

Vale dimensionar: os pacotes vêm compactados (~20–30 MB por ano), mas são
extraídos para uso, e cada ano-tipo ocupa algumas centenas de MB em disco.
A visão trimestral costuma tocar dois anos de ITR mais um de DFP.

Local padrão (via `platformdirs`, sem hardcode de SO):

- Windows: `%LOCALAPPDATA%\cvm-mcp`
- macOS: `~/Library/Caches/cvm-mcp`
- Linux: `~/.cache/cvm-mcp`

Para usar outro diretório (ex: ambientes restritos/CI), defina
`CVM_MCP_CACHE_DIR` antes de rodar o servidor.

## Limitações importantes

- **O 4T é derivado, não publicado.** A CVM não divulga o 4º trimestre
  isoladamente; o valor vem de `ano cheio − acumulado 9M`. Bate com o
  exercício por construção, mas não é um número que a empresa reportou.
- **Sem indicadores calculados.** Esta versão devolve contas contábeis
  publicadas, não margens, ROE ou EBITDA. O código de indicadores continua
  no repositório (`indicators.py`, `accounts.py`), sem estar ligado a
  nenhuma tool, para ser readaptado à base trimestral depois.
- **Sem dado de mercado**: a CVM não publica cotação, valor de mercado ou
  múltiplos (P/L, EV/EBITDA). Pedidos desse tipo ficam fora do escopo
  desta fonte.
- **Contas de estoque não se somam.** BPA e BPP são saldos: somar os 4
  trimestres de patrimônio líquido não produz nada com significado. Só as
  contas de fluxo podem ser acumuladas em 12 meses.
- **Nem toda empresa tem 4 trimestres** (IPO recente, suspensão,
  cancelamento de registro, atraso na entrega do ITR). A janela devolve os
  períodos que existirem, sem preencher buraco com zero.
- **Empresas do setor financeiro** usam um plano de contas de DRE
  diferente, então os códigos contábeis não são comparáveis linha a linha
  com os de empresas não financeiras.

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
  cvm_client.py   # busca de empresas e carregamento dos demonstrativos
  quarters.py     # montagem da janela trimestral e derivação do 4T
  models.py       # estruturas de dados (Company, Quarter)
  server.py       # servidor MCP (FastMCP) e definição das tools

  accounts.py     # (inativo) mapa do plano de contas -> itens financeiros
  indicators.py   # (inativo) cálculo de indicadores em base anual
```

`accounts.py` e `indicators.py` não são importados por nenhuma tool nesta
versão — ficam no repositório para servir de base quando os indicadores
forem reintroduzidos em base trimestral.
