# robo-pncp

Robô de coleta de dados públicos relacionados às unidades gestoras da Polícia
Federal, com persistência em PostgreSQL. Tudo roda em containers (`docker
compose up`).

## Fontes coletadas

Cada tabela carrega colunas `fonte`, `fonte_url` e `raw_json` para que a
procedência do dado nunca se perca. Cada endpoint vai para sua própria tabela
(não há mescla de origens).

| Origem                                 | Endpoint                                                                                                  | Tabela                                       |
|----------------------------------------|-----------------------------------------------------------------------------------------------------------|----------------------------------------------|
| PNCP — busca                           | `pncp.gov.br/api/search/?q={UG}&tipos_documento=edital`                                                   | `pncp.editais`                               |
| PNCP — itens do edital                 | `/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq}/itens`                                                     | `pncp.edital_itens`                          |
| PNCP — resultados do item              | `/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq}/itens/{n}/resultados`                                      | `pncp.edital_item_resultados`                |
| PNCP — atas do edital                  | `/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq}/atas`                                                      | `pncp.atas`                                  |
| Dados Abertos — hierarquia material    | `/modulo-material/4_consultarItemMaterial?codigoItem={cod}` (cadeia Grupo>Classe>PDM>Item embutida) | `dadosabertos.material_grupo`, `material_classe`, `material_pdm`, `material_item` |
| Dados Abertos — hierarquia serviço     | `/modulo-servico/6_consultarItemServico?codigoServico={cod}` (cadeia Seção>…>Item embutida) | `dadosabertos.servico_secao`, `servico_divisao`, `servico_grupo`, `servico_classe`, `servico_subclasse`, `servico_item` |
| Dados Abertos — ARP                     | `/modulo-arp/1_consultarARP` (filtro por `codigoUnidadeGerenciadora` + janela `dataVigenciaInicial` ≤365d) | `dadosabertos.arp`                           |
| Dados Abertos — itens da ARP           | `/modulo-arp/2_consultarARPItem`                                                                          | `dadosabertos.arp_itens`                     |
| Dados Abertos — unidades do item       | `/modulo-arp/3_consultarUnidadesItem`                                                                     | `dadosabertos.arp_item_unidades`             |
| Dados Abertos — empenhos/saldo do item | `/modulo-arp/4_consultarEmpenhosSaldoItem`                                                                | `dadosabertos.arp_item_empenho_saldo`        |
| Dados Abertos — adesões do item        | `/modulo-arp/5_consultarAdesoesItem`                                                                      | `dadosabertos.arp_item_adesoes`              |

> Paths confirmados via `https://dadosabertos.compras.gov.br/v3/api-docs` (swagger).
> Envelope de resposta: `{resultado:[...], totalRegistros, totalPaginas, paginasRestantes}`.
> `tamanhoPagina` aceito: 10–500. Constantes no topo de
> [`src/collectors/dados_abertos.py`](src/collectors/dados_abertos.py).
>
> **Hierarquia sob demanda:** em vez de baixar o catálogo inteiro (~342k materiais),
> o robô coleta a hierarquia **apenas dos itens que apareceram** nos editais
> (`pncp.edital_itens.catalogoCodigoItem`) e nas atas (`dadosabertos.arp_itens.codigo_item`).
> Para cada código, uma chamada ao endpoint de item devolve a cadeia completa
> (grupo→classe→pdm→item / seção→…→item), que é gravada em todos os níveis.
> Por isso essa é a **última etapa** do pipeline (precisa dos itens já coletados).
>
> As ARPs são varridas por **unidade gestora da PF** (códigos em `UNIDADES_PF`)
> em janelas de 365 dias a partir de `ARP_ANO_INICIAL`.

## Unidades cobertas

Lista completa em [`src/config.py`](src/config.py) (`UNIDADES_PF`). Cobre as
SRs estaduais, DLOG, DTI, DCI, DIP, DIREN-ANP, DITEC e as DPFs descentralizadas.

## Paralelismo

O coletor processa **`WORKERS` unidades da PF em paralelo** (default `4`)
usando `ThreadPoolExecutor`:

- `coletar_pncp_por_ug` — `WORKERS` unidades da PF em paralelo; **dentro de cada
  UG** as sub-etapas rodam **sequencialmente**: editais → itens/resultados → atas.
  Isso limita a concorrência a `WORKERS` requisições simultâneas (1 por UG),
  bem mais gentil com o rate-limit do PNCP.
- Dados Abertos ARP — `WORKERS` pares (unidade PF × janela), depois empenhos/unidades/adesões por item.
- Hierarquia sob demanda — `WORKERS` códigos de material/serviço resolvidos em paralelo.

A ordem **entre etapas** continua sequencial (PNCP por UG → ARP → hierarquia) —
só paralelizamos dentro de cada etapa. A hierarquia vem por último porque depende
dos códigos de catálogo já coletados.

Thread-safety:
- Pool de conexões PG via `psycopg_pool.ConnectionPool` (`min=1`, `max=WORKERS+2`).
- `httpx.Client` é thread-safe (singleton).
- `obs_logger` usa `queue.Queue` (thread-safe) + worker dedicado.
- Exceção em um worker é capturada por item — não derruba a rodada.

## Estratégia de coleta sem perda

- Tabelas separadas por endpoint.
- Cada linha guarda `raw_json` (`JSONB`) com o payload original.
- `fonte` (slug curto, ex.: `pncp_v1_atas`) e `fonte_url` (URL chamada).
- `UPSERT` por chave natural (`numero_controle_pncp`, IDs, etc.) → atualiza
  os dados sem perder a procedência.
- Tabelas com prefixo de origem (`pncp_*`, `dadosabertos_*`, `meta_*`) num único schema `public`.

## Como rodar

```bash
cp .env.example .env
docker compose up -d --build
docker compose logs -f collector
```

PostgreSQL fica disponível em `localhost:5432` (usuário/senha/db conforme
`.env`). O schema é criado automaticamente na primeira subida via volume de
init.

### Modos de execução

- `RUN_MODE=loop` (default) → coleta a cada `LOOP_INTERVAL_SECONDS` (6h).
- `RUN_MODE=once` → uma rodada e o container encerra.

### Variáveis principais (`.env`)

| Variável                | Default | Função                                           |
|-------------------------|---------|--------------------------------------------------|
| `POSTGRES_USER/PASSWORD/DB` | `pncp` | Credenciais do banco                          |
| `POSTGRES_PORT`         | `5432`  | Porta exposta no host                           |
| `RUN_MODE`              | `loop`  | `loop` ou `once`                                |
| `LOOP_INTERVAL_SECONDS` | `21600` | Intervalo entre rodadas (6h)                    |
| `PAGE_SIZE`             | `50`    | Tamanho da página nas APIs paginadas            |
| `HTTP_TIMEOUT`          | `60`    | Timeout HTTP (s)                                |
| `LOG_LEVEL`             | `INFO`  | `DEBUG`, `INFO`, `WARNING`, `ERROR`             |
| `WORKERS`               | `4`     | Threads concorrentes. Pool PG = `WORKERS + 2`.   |
| `DA_PAGE_SIZE`          | `500`   | `tamanhoPagina` do Dados Abertos (10–500).       |
| `ARP_ANO_INICIAL`       | `2023`  | Ano inicial da varredura de ARPs.                |

## Observabilidade

O coletor envia eventos para o projeto [observabilidade](../observabilidade)
via `POST /api/logs` em uma thread separada (fire-and-forget) — se a API estiver
fora, a coleta continua.

### Eventos emitidos

| `identifier` | `identifier_2` | `identifier_3` | `type`              | Quando             |
|--------------|----------------|----------------|---------------------|--------------------|
| `EXECUCAO`   | id da execução | —              | `success` / `error` | Início/fim de cada rodada |
| `ETAPA`      | nome da etapa  | —              | `success` / `error` | Cada etapa do pipeline    |
| `UNIDADE`    | sigla PF       | código UG      | `success` / `error` | Coleta de editais por unidade |
| `EDITAL`     | sigla PF       | nº controle PNCP | `success`         | Cada edital gravado       |
| `ATA`        | CNPJ órgão     | nº controle PNCP | `success`         | Cada ata gravada          |
| `API`        | tag da API     | URL chamada    | `success` / `warning` / `error` | Toda chamada HTTP |

Tags de API: `PNCP_EDITAIS`, `PNCP_ITENS`, `PNCP_DETALHE_ITEM`, `PNCP_ATAS`,
`DADOSABERTOS_MATERIAL`, `DADOSABERTOS_SERVICO`, `DADOSABERTOS_ARP`.

### Dashboard

O backend da observabilidade cria automaticamente o dashboard **"Robô PNCP -
Visão Geral"** no startup (ver `app/backend/app/seed_pncp.py`). Cards:

- KPIs: Execuções OK, Falhas, Editais, Atas, Tempo médio/etapa
- Duração média por etapa (bar)
- Falhas por etapa (bar)
- Requisições API por tag — sucesso e falha (bar)
- Editais por unidade da PF (bar)
- Erros por unidade da PF (bar)
- Distribuição por tipo de evento (pie)

### Rede docker

O `collector` se conecta à rede externa `observabilidade_network`. Suba
primeiro o stack da observabilidade — depois `docker compose up -d` aqui.
Se `OBS_ENABLED=false`, o robô roda normalmente sem enviar nada.

## Consultas úteis

```sql
-- Quantos editais por unidade da PF
SELECT unidade_sigla_pf, COUNT(*) FROM pncp_editais GROUP BY 1 ORDER BY 2 DESC;

-- Itens com resultado homologado
SELECT COUNT(*) FROM pncp_edital_item_resultados;

-- Historico de execucoes
SELECT id, iniciado_em, finalizado_em, status, contadores FROM meta_execucao ORDER BY id DESC LIMIT 10;
```

## Estrutura

```
.
├── docker-compose.yml      # postgres + collector
├── Dockerfile              # imagem do collector (python 3.12)
├── requirements.txt
├── .env.example
├── db/
│   └── schema.sql          # DDL completo (criado no init do postgres)
└── src/
    ├── main.py             # orquestra a rodada
    ├── config.py           # unidades PF, env vars
    ├── db.py               # conexao, upsert generico, metadados de execucao
    ├── http_client.py      # httpx + tenacity (retries, backoff)
    └── collectors/
        ├── pncp.py
        └── dados_abertos.py
```
