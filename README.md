# cvm-mcp

Servidor [MCP](https://modelcontextprotocol.io) que busca e trata dados
financeiros **direto das fontes oficiais**, sem depender de terceiros:

- **CVM** (Brasil): Portal de Dados Abertos (`dados.cvm.gov.br`)
- **SEC/EDGAR** (EUA): APIs de dados XBRL (`data.sec.gov`). Veja a seção
  [Empresas dos EUA (SEC)](#empresas-dos-eua-sec).
 Expõe tools para um
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

## Empresas dos EUA (SEC)

As tools com prefixo `sec_` trazem as demonstrações de companhias
registradas na SEC, a partir das APIs oficiais e gratuitas de XBRL. O
formato da resposta é o mesmo das tools da CVM (`periodos`, `derivado`,
`contas`, `avisos`).

| Tool | Quando usar |
|---|---|
| `sec_buscar_empresa` | Resolver ticker/CIK/nome antes de qualquer análise |
| `sec_analisar_empresa` | Pedido genérico: DRE padronizada dos últimos 4 trimestres |
| `sec_obter_demonstrativo_trimestral` | DRE, BPA, BPP ou DFC, por quantos trimestres quiser |
| `sec_obter_demonstrativo_anual` | Exercício fiscal fechado (10-K, 20-F, 40-F) |
| `sec_obter_conta_xbrl` | Qualquer tag XBRL fora do mapa padrão (ex: `LongTermDebt`) |

### Configuração obrigatória: identificação

A SEC exige que todo acesso automatizado se identifique com **nome e
e-mail** no User-Agent ([regra da SEC](https://www.sec.gov/os/accessing-edgar-data));
sem isso ela responde 403. O valor é pessoal, por isso vem de variável de
ambiente e **nunca fica no código**:

```json
{
  "mcpServers": {
    "cvm": {
      "command": "cvm-mcp",
      "env": { "SEC_MCP_USER_AGENT": "Seu Nome seu@email.com" }
    }
  }
}
```

Sem a variável, as tools da CVM continuam funcionando normalmente; as da
SEC devolvem um aviso explicando como configurar.

### Fontes usadas

| Endpoint | Para quê |
|---|---|
| `www.sec.gov/files/company_tickers.json` | Ticker → CIK |
| `data.sec.gov/submissions/CIK##########.json` | Cadastro: setor (SIC), fim do exercício fiscal, bolsas, tipo de emissor |
| `data.sec.gov/api/xbrl/companyfacts/CIK##########.json` | Todos os valores XBRL já reportados pela empresa |

### Como os dados são tratados

- **Padronização de contas** (`sec/mapping.py`): cada empresa escolhe suas
  tags XBRL (a receita pode ser `Revenues`, `RevenueFromContractWith...`,
  `SalesRevenueNet`...). Cada conta padrão tem uma lista ordenada de tags
  candidatas, US-GAAP e IFRS, e a resposta informa em `tag_xbrl` qual foi
  usada. Os códigos (1 = ativo, 2 = passivo e PL, 3 = resultado, 6 = caixa)
  imitam a estrutura da CVM para leitura lado a lado, mas não são oficiais.
- **4º trimestre derivado**: `anual (10-K) − acumulado até o 3T`, na mesma
  tag, marcado com `derivado: true`, como na CVM.
- **Fluxo de caixa acumulado**: o 10-Q costuma trazer o DFC só acumulado no
  ano (3, 6, 9 meses); o trimestre isolado sai da diferença entre
  acumulados e também vem com `derivado: true`.
- **LPA e número de ações** nunca são derivados por subtração (não é
  aritmeticamente válido); no 4T derivado ficam ausentes.
- **Reapresentações**: quando o mesmo período foi reportado com valores
  diferentes (emenda ou comparativo corrigido), fica a entrega mais recente,
  com `reapresentado: true`.
- **Rastreabilidade**: toda conta traz `formulario`, `acessao` (número de
  acesso no EDGAR) e `arquivado_em`.
- **Exercício fiscal da empresa**: a Apple fecha em setembro, varejistas em
  janeiro. O rótulo (`4T25`) usa o ano fiscal que a empresa declarou, e vem
  sempre com `inicio`/`fim`.
- **Checagem do balanço**: se ativo total ≠ passivo + PL (tolerância de
  0,5%), sai um aviso.

### Uso seguro da API

- **Limite de taxa**: no máximo 8 requisições/s (a SEC permite 10).
- **Cache local** em `<cache_dir>/sec`: dentro de algumas horas nem consulta
  a SEC; depois revalida por ETag/Last-Modified. Se a SEC estiver fora do
  ar, usa a cópia em cache e avisa.
- **Retentativa** com espera crescente para respostas 429/5xx.
- Só entram valores de formulários de demonstrações (10-K, 10-Q, 20-F,
  40-F, 6-K e emendas). Fatos de 8-K, prospectos etc. são descartados.

### Limitações da fonte SEC

- **Emissores estrangeiros** (20-F/40-F, ex: Nu Holdings `NU`): a SEC só
  exige XBRL no relatório anual. Os trimestres entregues em 6-K
  normalmente não são estruturados, então a visão trimestral pode vir
  vazia; use `sec_obter_demonstrativo_anual`.
- **Sinal**: valores como no XBRL, com custos e despesas positivos (na CVM
  vêm negativos).
- **Sem dado de mercado**: cotação, valor de mercado e múltiplos não vêm da
  SEC.
- **Bancos e seguradoras** usam tags próprias; o mapa cobre as principais
  (receita de juros, provisão para perdas, carteira, depósitos), e o resto
  sai por `sec_obter_conta_xbrl`.

### Testes

```bash
pip install -e ".[dev]"
pytest
```

Os testes rodam offline, com empresas sintéticas que reproduzem o formato
real das APIs da SEC (exercício calendário, exercício em setembro, emissor
estrangeiro IFRS, reapresentação, DFC acumulado).

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
  sec/            # fonte SEC/EDGAR (EUA)
    config.py     # endpoints, limites e User-Agent (variável de ambiente)
    http.py       # download com limite de taxa, retentativa e cache condicional
    companies.py  # ticker/CIK → cadastro
    facts.py      # leitura e consolidação dos company facts XBRL
    mapping.py    # mapa de tags XBRL → contas padronizadas
    periods.py    # calendário fiscal, trimestres e derivações
    service.py    # monta as respostas das tools sec_*

  accounts.py     # (inativo) mapa do plano de contas -> itens financeiros
  indicators.py   # (inativo) cálculo de indicadores em base anual
```

`accounts.py` e `indicators.py` não são importados por nenhuma tool nesta
versão — ficam no repositório para servir de base quando os indicadores
forem reintroduzidos em base trimestral.
