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
| PNCP — contratos do edital             | `/api/pncp/v1/orgaos/{cnpj}/contratos/contratacao/{ano}/{seq}/`                                            | `pncp.contratos`                             |
| Contratos Comprasnet — contrato base   | `contratos.comprasnet.gov.br/api/contrato/ugorigem/{UG}/numeroano/{NUMEROANO}`                            | `comprasnet.contratos`                       |
| Contratos Comprasnet — sub-rotas       | `/api/contrato/{id}/{historico,empenhos,cronograma,garantias,itens,prepostos,responsaveis,...}`           | `comprasnet.contrato_subrota`                |
| Dados Abertos — hierarquia material    | `/modulo-material/{1_consultarGrupoMaterial,2_consultarClasseMaterial,3_consultarPdmMaterial,4_consultarItemMaterial}` | `dadosabertos.material_grupo`, `material_classe`, `material_pdm`, `material_item` |
| Dados Abertos — hierarquia serviço     | `/modulo-servico/{1_consultarSecaoServico,2_consultarDivisaoServico,3_consultarGrupoServico,4_consultarClasseServico,5_consultarSubClasseServico,6_consultarItemServico}` | `dadosabertos.servico_secao`, `servico_divisao`, `servico_grupo`, `servico_classe`, `servico_subclasse`, `servico_item` |
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
> A hierarquia de material/serviço é **dado de referência global** (não filtra por
> PF). As ARPs são varridas por **unidade gestora da PF** (códigos em `UNIDADES_PF`)
> em janelas de 365 dias a partir de `ARP_ANO_INICIAL`. O catálogo de itens de
> material (~342k) pode ser desligado com `DA_MATERIAL_ITENS=false`.

## Unidades cobertas

Lista completa em [`src/config.py`](src/config.py) (`UNIDADES_PF`). Cobre as
SRs estaduais, DLOG, DTI, DCI, DIP, DIREN-ANP, DITEC e as DPFs descentralizadas.

## Paralelismo

O coletor processa **`WORKERS` unidades/editais em paralelo** (default `4`)
usando `ThreadPoolExecutor`:

- `coletar_editais` — `WORKERS` unidades da PF simultaneamente.
- `coletar_itens_e_resultados` — `WORKERS` editais (e depois itens com resultado) simultaneamente.
- `coletar_atas` / `coletar_contratos` — `WORKERS` editais simultaneamente.
- Comprasnet (`coletar_contratos_e_subrotas`) — `WORKERS` contratos simultaneamente.
- Hierarquia material/serviço — os níveis (grupo/classe/pdm/item…) coletados em paralelo.
- Dados Abertos ARP — `WORKERS` pares (unidade PF × janela), depois empenhos/unidades/adesões por item.

A ordem **entre etapas** continua sequencial (editais → drill-downs → contratos →
ARP) — só paralelizamos dentro de cada etapa.

Thread-safety:
- Pool de conexões PG via `psycopg_pool.ConnectionPool` (`min=1`, `max=WORKERS+2`).
- `httpx.Client` é thread-safe (singleton).
- `obs_logger` usa `queue.Queue` (thread-safe) + worker dedicado.
- Exceção em um worker é capturada por item — não derruba a rodada.

## Estratégia de coleta sem perda

- Tabelas separadas por endpoint.
- Cada linha guarda `raw_json` (`JSONB`) com o payload original.
- `fonte` (slug curto, ex.: `pncp_v1_contratos`) e `fonte_url` (URL chamada).
- `UPSERT` por chave natural (`numero_controle_pncp`, IDs, etc.) → atualiza
  os dados sem perder a procedência.
- Schemas separados: `pncp`, `comprasnet`, `dadosabertos`, `meta`.

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
| `DA_MATERIAL_ITENS`     | `true`  | Coletar catálogo de itens de material (~342k).   |
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
| `CONTRATO`   | CNPJ órgão     | nº controle PNCP | `success`         | Cada contrato PNCP gravado |
| `API`        | tag da API     | URL chamada    | `success` / `warning` / `error` | Toda chamada HTTP |

Tags de API: `PNCP_SEARCH`, `PNCP_V1_ITENS`, `PNCP_V1_RESULTADOS`, `PNCP_V1_ATAS`,
`PNCP_V1_CONTRATOS`, `COMPRASNET_CONTRATOS`, `COMPRASNET_SUBROTA`,
`DADOSABERTOS_MATERIAL`, `DADOSABERTOS_SERVICO`, `DADOSABERTOS_ARP`.

### Dashboard

O backend da observabilidade cria automaticamente o dashboard **"Robô PNCP -
Visão Geral"** no startup (ver `app/backend/app/seed_pncp.py`). Cards:

- KPIs: Execuções OK, Falhas, Editais, Contratos, Atas, Tempo médio/etapa
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
SELECT unidade_sigla_pf, COUNT(*) FROM pncp.editais GROUP BY 1 ORDER BY 2 DESC;

-- Contratos PNCP cruzados com a base do Comprasnet
SELECT p.numero_controle_pncp, p.numero_contrato_empenho, p.ano_contrato,
       c.id AS contrato_comprasnet_id, c.valor_global
  FROM pncp.contratos p
  LEFT JOIN comprasnet.contratos c
    ON c.numero_norm = LPAD(REGEXP_REPLACE(p.numero_contrato_empenho, '\D', '', 'g'), 5, '0')
                       || LPAD(p.ano_contrato::text, 4, '0');

-- Sub-rotas que voltaram dados
SELECT subrota, COUNT(*) FROM comprasnet.contrato_subrota GROUP BY 1 ORDER BY 2 DESC;

-- Historico de execucoes
SELECT id, iniciado_em, finalizado_em, status, contadores FROM meta.execucao ORDER BY id DESC LIMIT 10;
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
        ├── comprasnet_contratos.py
        └── dados_abertos.py
```
