-- =========================================================================
-- Schema do Robo PNCP - tudo em um schema unico (public).
-- Nome das tabelas: {origem}_{nome} (ex: pncp_editais, comprasnet_contratos).
--
-- Cada tabela carrega colunas de procedencia:
--   fonte       -> identificador curto da origem (ex: 'pncp_search')
--   fonte_url   -> URL completa de onde o registro foi obtido
--   raw_json    -> payload bruto retornado pela API
--   coletado_em -> timestamp da coleta
-- Tabelas distintas por endpoint (sem mesclar dados de fontes diferentes).
-- =========================================================================

-- ---------------------------------------------------------------------
-- Metadados de coleta
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS meta_unidades_pf (
    sigla         TEXT PRIMARY KEY,
    codigo_unidade TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS meta_execucao (
    id             BIGSERIAL PRIMARY KEY,
    iniciado_em    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finalizado_em  TIMESTAMPTZ,
    status         TEXT NOT NULL DEFAULT 'rodando',
    erro           TEXT,
    contadores     JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- =========================================================================
-- PNCP - pncp.gov.br
-- =========================================================================

-- /api/search/?q=...&tipos_documento=edital  (site search)
CREATE TABLE IF NOT EXISTS pncp_editais (
    numero_controle_pncp     TEXT PRIMARY KEY,
    orgao_cnpj               TEXT NOT NULL,
    orgao_nome               TEXT,
    unidade_codigo           TEXT,
    unidade_nome             TEXT,
    unidade_sigla_pf         TEXT,
    ano                      TEXT,
    numero_sequencial        TEXT,
    title                    TEXT,
    description              TEXT,
    item_url                 TEXT,
    document_type            TEXT,
    modalidade_id            TEXT,
    modalidade_nome          TEXT,
    situacao_id              TEXT,
    situacao_nome            TEXT,
    tipo_id                  TEXT,
    tipo_nome                TEXT,
    data_publicacao_pncp     TIMESTAMPTZ,
    data_atualizacao_pncp    TIMESTAMPTZ,
    data_inicio_vigencia     TIMESTAMPTZ,
    data_fim_vigencia        TIMESTAMPTZ,
    created_at_api           TIMESTAMPTZ,
    fonte                    TEXT NOT NULL,
    fonte_url                TEXT NOT NULL,
    raw_json                 JSONB NOT NULL,
    coletado_em              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_pncp_editais_unidade  ON pncp_editais (unidade_codigo);
CREATE INDEX IF NOT EXISTS idx_pncp_editais_orgao    ON pncp_editais (orgao_cnpj);
CREATE INDEX IF NOT EXISTS idx_pncp_editais_ano_seq  ON pncp_editais (orgao_cnpj, ano, numero_sequencial);

-- /api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq}/itens
CREATE TABLE IF NOT EXISTS pncp_edital_itens (
    orgao_cnpj            TEXT NOT NULL,
    ano                   TEXT NOT NULL,
    numero_sequencial     TEXT NOT NULL,
    numero_item           INTEGER NOT NULL,
    descricao             TEXT,
    material_ou_servico   TEXT,
    material_ou_servico_nome TEXT,
    valor_unitario_estimado NUMERIC(20,4),
    quantidade            NUMERIC(20,4),
    unidade_medida        TEXT,
    situacao_id           INTEGER,
    situacao_nome         TEXT,
    tem_resultado         BOOLEAN,
    data_inclusao         TIMESTAMPTZ,
    data_atualizacao      TIMESTAMPTZ,
    fonte                 TEXT NOT NULL,
    fonte_url             TEXT NOT NULL,
    raw_json              JSONB NOT NULL,
    coletado_em           TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (orgao_cnpj, ano, numero_sequencial, numero_item)
);

-- /api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq}/itens/{n}/resultados
CREATE TABLE IF NOT EXISTS pncp_edital_item_resultados (
    orgao_cnpj            TEXT NOT NULL,
    ano                   TEXT NOT NULL,
    numero_sequencial     TEXT NOT NULL,
    numero_item           INTEGER NOT NULL,
    sequencial_resultado  INTEGER NOT NULL,
    ni_fornecedor         TEXT,
    tipo_pessoa           TEXT,
    nome_razao_social     TEXT,
    codigo_pais           TEXT,
    porte_fornecedor_id   INTEGER,
    porte_fornecedor_nome TEXT,
    natureza_juridica_id  TEXT,
    natureza_juridica_nome TEXT,
    quantidade_homologada NUMERIC(20,4),
    valor_unitario_homologado NUMERIC(20,4),
    ordem_classificacao_srp INTEGER,
    data_resultado        DATE,
    situacao_id           INTEGER,
    situacao_nome         TEXT,
    numero_controle_pncp_compra TEXT,
    data_inclusao         TIMESTAMPTZ,
    data_atualizacao      TIMESTAMPTZ,
    fonte                 TEXT NOT NULL,
    fonte_url             TEXT NOT NULL,
    raw_json              JSONB NOT NULL,
    coletado_em           TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (orgao_cnpj, ano, numero_sequencial, numero_item, sequencial_resultado)
);

-- /api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq}/atas
CREATE TABLE IF NOT EXISTS pncp_atas (
    numero_controle_pncp        TEXT PRIMARY KEY,
    numero_controle_pncp_compra TEXT,
    orgao_cnpj                  TEXT,
    orgao_razao_social          TEXT,
    unidade_codigo              TEXT,
    unidade_nome                TEXT,
    numero_ata                  TEXT,
    ano_ata                     INTEGER,
    sequencial_ata              INTEGER,
    data_assinatura             DATE,
    data_vigencia_inicio        DATE,
    data_vigencia_fim           DATE,
    data_cancelamento           DATE,
    cancelado                   BOOLEAN,
    data_publicacao_pncp        TIMESTAMPTZ,
    data_inclusao               TIMESTAMPTZ,
    data_atualizacao            TIMESTAMPTZ,
    data_atualizacao_global     TIMESTAMPTZ,
    modalidade_nome             TEXT,
    objeto_compra               TEXT,
    informacao_complementar     TEXT,
    fonte                       TEXT NOT NULL,
    fonte_url                   TEXT NOT NULL,
    raw_json                    JSONB NOT NULL,
    coletado_em                 TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_pncp_atas_compra ON pncp_atas (numero_controle_pncp_compra);

-- =========================================================================
-- Contratos.comprasnet.gov.br
-- Endpoint: /api/contrato/ug/{ug}
-- Sub-rotas coletadas: historico, empenhos, itens, faturas.
-- =========================================================================

CREATE TABLE IF NOT EXISTS comprasnet_contratos (
    id                       BIGINT PRIMARY KEY,
    -- Match com PNCP por (unidade_compra, modalidade prefix, licitacao_numero=seq/ano).
    -- NULL se o edital correspondente nao foi encontrado em pncp_editais.
    id_contrato_edital_pncp  TEXT,
    receita_despesa          TEXT,
    numero                   TEXT,
    codigo_tipo              TEXT,
    tipo                     TEXT,
    subtipo                  TEXT,
    prorrogavel              TEXT,
    situacao                 TEXT,
    justificativa_inativo    TEXT,
    categoria                TEXT,
    subcategoria             TEXT,
    unidades_requisitantes   TEXT,
    processo                 TEXT,
    objeto                   TEXT,
    amparo_legal             TEXT,
    informacao_complementar  TEXT,
    codigo_modalidade        TEXT,
    modalidade               TEXT,
    unidade_compra           TEXT,
    licitacao_numero         TEXT,
    sistema_origem_licitacao TEXT,
    -- orgao / unidade gestora de origem
    orgao_origem_codigo      TEXT,
    orgao_origem_nome        TEXT,
    ug_origem_codigo         TEXT,
    ug_origem_nome           TEXT,
    ug_origem_nome_resumido  TEXT,
    -- orgao / unidade gestora atual
    orgao_codigo             TEXT,
    orgao_nome               TEXT,
    ug_codigo                TEXT,
    ug_nome                  TEXT,
    ug_nome_resumido         TEXT,
    -- fornecedor
    fornecedor_tipo          TEXT,
    fornecedor_cnpj_cpf      TEXT,
    fornecedor_nome          TEXT,
    -- datas / valores
    data_assinatura          DATE,
    data_publicacao          DATE,
    data_proposta_comercial  DATE,
    vigencia_inicio          DATE,
    vigencia_fim             DATE,
    valor_inicial            NUMERIC(20,4),
    valor_global             NUMERIC(20,4),
    valor_parcela            NUMERIC(20,4),
    valor_acumulado          NUMERIC(20,4),
    num_parcelas             INTEGER,
    fonte                    TEXT NOT NULL,
    fonte_url                TEXT NOT NULL,
    raw_json                 JSONB NOT NULL,
    coletado_em              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_comprasnet_contratos_ug      ON comprasnet_contratos (ug_origem_codigo);
CREATE INDEX IF NOT EXISTS idx_comprasnet_contratos_edital  ON comprasnet_contratos (id_contrato_edital_pncp);
CREATE INDEX IF NOT EXISTS idx_comprasnet_contratos_match   ON comprasnet_contratos (unidade_compra, licitacao_numero);

-- Sub-rotas: historico, empenhos, itens, faturas
CREATE TABLE IF NOT EXISTS comprasnet_contrato_subrota (
    contrato_id   BIGINT NOT NULL,
    subrota       TEXT   NOT NULL,        -- 'historico','empenhos','itens','faturas'
    item_id       TEXT   NOT NULL,        -- id do item ou hash; quando a API nao da id, usamos posicao
    fonte         TEXT   NOT NULL,
    fonte_url     TEXT   NOT NULL,
    raw_json      JSONB  NOT NULL,
    coletado_em   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (contrato_id, subrota, item_id)
);
CREATE INDEX IF NOT EXISTS idx_comprasnet_contrato_subrota_rota ON comprasnet_contrato_subrota (subrota);

-- =========================================================================
-- Dados Abertos Comprasgov - dadosabertos.compras.gov.br
-- Paths confirmados via /v3/api-docs (swagger). Envelope de resposta:
--   {resultado:[...], totalRegistros, totalPaginas, paginasRestantes}
-- =========================================================================

-- ----- Hierarquia de Material: Grupo > Classe > PDM > Item -----
CREATE TABLE IF NOT EXISTS dadosabertos_material_grupo (
    codigo_grupo  TEXT PRIMARY KEY,
    nome_grupo    TEXT,
    status_grupo  BOOLEAN,
    data_atualizacao TIMESTAMPTZ,
    fonte         TEXT NOT NULL,
    fonte_url     TEXT NOT NULL,
    raw_json      JSONB NOT NULL,
    coletado_em   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dadosabertos_material_classe (
    codigo_classe TEXT PRIMARY KEY,
    codigo_grupo  TEXT,
    nome_grupo    TEXT,
    nome_classe   TEXT,
    status_classe BOOLEAN,
    data_atualizacao TIMESTAMPTZ,
    fonte         TEXT NOT NULL,
    fonte_url     TEXT NOT NULL,
    raw_json      JSONB NOT NULL,
    coletado_em   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_dadosabertos_material_classe_grupo ON dadosabertos_material_classe (codigo_grupo);

CREATE TABLE IF NOT EXISTS dadosabertos_material_pdm (
    codigo_pdm    TEXT PRIMARY KEY,
    codigo_classe TEXT,
    nome_classe   TEXT,
    codigo_grupo  TEXT,
    nome_grupo    TEXT,
    nome_pdm      TEXT,
    status_pdm    BOOLEAN,
    data_atualizacao TIMESTAMPTZ,
    fonte         TEXT NOT NULL,
    fonte_url     TEXT NOT NULL,
    raw_json      JSONB NOT NULL,
    coletado_em   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_dadosabertos_material_pdm_classe ON dadosabertos_material_pdm (codigo_classe);

CREATE TABLE IF NOT EXISTS dadosabertos_material_item (
    codigo_item     TEXT PRIMARY KEY,
    codigo_pdm      TEXT,
    nome_pdm        TEXT,
    codigo_classe   TEXT,
    nome_classe     TEXT,
    codigo_grupo    TEXT,
    nome_grupo      TEXT,
    descricao_item  TEXT,
    status_item     BOOLEAN,
    item_sustentavel BOOLEAN,
    codigo_ncm      TEXT,
    descricao_ncm   TEXT,
    fonte           TEXT NOT NULL,
    fonte_url       TEXT NOT NULL,
    raw_json        JSONB NOT NULL,
    coletado_em     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_dadosabertos_material_item_pdm    ON dadosabertos_material_item (codigo_pdm);
CREATE INDEX IF NOT EXISTS idx_dadosabertos_material_item_classe ON dadosabertos_material_item (codigo_classe);

-- ----- Hierarquia de Servico: Secao > Divisao > Grupo > Classe > SubClasse > Item -----
CREATE TABLE IF NOT EXISTS dadosabertos_servico_secao (
    codigo_secao  TEXT PRIMARY KEY,
    nome_secao    TEXT,
    status_secao  BOOLEAN,
    data_atualizacao TIMESTAMPTZ,
    fonte         TEXT NOT NULL,
    fonte_url     TEXT NOT NULL,
    raw_json      JSONB NOT NULL,
    coletado_em   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dadosabertos_servico_divisao (
    codigo_divisao TEXT PRIMARY KEY,
    codigo_secao   TEXT,
    nome_secao     TEXT,
    nome_divisao   TEXT,
    status_divisao BOOLEAN,
    data_atualizacao TIMESTAMPTZ,
    fonte          TEXT NOT NULL,
    fonte_url      TEXT NOT NULL,
    raw_json       JSONB NOT NULL,
    coletado_em    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_dadosabertos_servico_divisao_secao ON dadosabertos_servico_divisao (codigo_secao);

CREATE TABLE IF NOT EXISTS dadosabertos_servico_grupo (
    codigo_grupo  TEXT PRIMARY KEY,
    codigo_divisao TEXT,
    nome_divisao  TEXT,
    nome_secao    TEXT,
    nome_grupo    TEXT,
    status_grupo  BOOLEAN,
    data_atualizacao TIMESTAMPTZ,
    fonte         TEXT NOT NULL,
    fonte_url     TEXT NOT NULL,
    raw_json      JSONB NOT NULL,
    coletado_em   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_dadosabertos_servico_grupo_div ON dadosabertos_servico_grupo (codigo_divisao);

CREATE TABLE IF NOT EXISTS dadosabertos_servico_classe (
    codigo_classe TEXT PRIMARY KEY,
    codigo_grupo  TEXT,
    nome_grupo    TEXT,
    nome_classe   TEXT,
    status_classe BOOLEAN,
    data_atualizacao TIMESTAMPTZ,
    fonte         TEXT NOT NULL,
    fonte_url     TEXT NOT NULL,
    raw_json      JSONB NOT NULL,
    coletado_em   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_dadosabertos_servico_classe_grupo ON dadosabertos_servico_classe (codigo_grupo);

CREATE TABLE IF NOT EXISTS dadosabertos_servico_subclasse (
    codigo_subclasse TEXT PRIMARY KEY,
    codigo_classe    TEXT,
    nome_classe      TEXT,
    nome_subclasse   TEXT,
    status_subclasse BOOLEAN,
    data_atualizacao TIMESTAMPTZ,
    fonte            TEXT NOT NULL,
    fonte_url        TEXT NOT NULL,
    raw_json         JSONB NOT NULL,
    coletado_em      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_dadosabertos_servico_subclasse_classe ON dadosabertos_servico_subclasse (codigo_classe);

CREATE TABLE IF NOT EXISTS dadosabertos_servico_item (
    codigo_servico   TEXT PRIMARY KEY,
    codigo_subclasse TEXT,
    nome_subclasse   TEXT,
    codigo_classe    TEXT,
    nome_classe      TEXT,
    codigo_grupo     TEXT,
    nome_grupo       TEXT,
    codigo_divisao   TEXT,
    nome_divisao     TEXT,
    codigo_secao     TEXT,
    nome_secao       TEXT,
    nome_servico     TEXT,
    codigo_cpc       TEXT,
    status_servico   BOOLEAN,
    data_atualizacao TIMESTAMPTZ,
    fonte            TEXT NOT NULL,
    fonte_url        TEXT NOT NULL,
    raw_json         JSONB NOT NULL,
    coletado_em      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_dadosabertos_servico_item_classe ON dadosabertos_servico_item (codigo_classe);

-- ----- ARP (Ata de Registro de Precos) - modulo-arp -----
-- Chave natural: (numero_ata, unidade_gerenciadora). Ex.: ('00014/2025','200334')
CREATE TABLE IF NOT EXISTS dadosabertos_arp (
    numero_ata               TEXT NOT NULL,
    unidade_gerenciadora     TEXT NOT NULL,
    nome_unidade_gerenciadora TEXT,
    codigo_orgao             TEXT,
    nome_orgao               TEXT,
    link_ata_pncp            TEXT,
    link_compra_pncp         TEXT,
    numero_compra            TEXT,
    ano_compra               TEXT,
    codigo_modalidade        TEXT,
    nome_modalidade          TEXT,
    data_assinatura          DATE,
    data_vigencia_inicial    DATE,
    data_vigencia_final      DATE,
    valor_total              NUMERIC(20,4),
    status_ata               TEXT,
    objeto                   TEXT,
    fonte                    TEXT NOT NULL,
    fonte_url                TEXT NOT NULL,
    raw_json                 JSONB NOT NULL,
    coletado_em              TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (numero_ata, unidade_gerenciadora)
);

CREATE TABLE IF NOT EXISTS dadosabertos_arp_itens (
    numero_ata               TEXT NOT NULL,
    unidade_gerenciadora     TEXT NOT NULL,
    numero_item              TEXT NOT NULL,
    ni_fornecedor            TEXT NOT NULL DEFAULT '',
    codigo_item              TEXT,
    descricao_item           TEXT,
    tipo_item                TEXT,
    quantidade_homologada    NUMERIC(20,4),
    classificacao_fornecedor TEXT,
    nome_fornecedor          TEXT,
    numero_compra            TEXT,
    ano_compra               TEXT,
    codigo_modalidade        TEXT,
    data_vigencia_inicial    DATE,
    data_vigencia_final      DATE,
    fonte                    TEXT NOT NULL,
    fonte_url                TEXT NOT NULL,
    raw_json                 JSONB NOT NULL,
    coletado_em              TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (numero_ata, unidade_gerenciadora, numero_item, ni_fornecedor)
);
CREATE INDEX IF NOT EXISTS idx_dadosabertos_arp_itens_ata ON dadosabertos_arp_itens (numero_ata, unidade_gerenciadora);

CREATE TABLE IF NOT EXISTS dadosabertos_arp_item_empenho_saldo (
    numero_ata             TEXT NOT NULL,
    unidade_gerenciadora   TEXT NOT NULL,
    numero_item            TEXT NOT NULL,
    unidade                TEXT NOT NULL DEFAULT '',
    tipo                   TEXT NOT NULL DEFAULT '',
    quantidade_registrada  NUMERIC(20,4),
    quantidade_empenhada   NUMERIC(20,4),
    saldo_empenho          NUMERIC(20,4),
    data_atualizacao       TIMESTAMPTZ,
    fonte                  TEXT NOT NULL,
    fonte_url              TEXT NOT NULL,
    raw_json               JSONB NOT NULL,
    coletado_em            TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (numero_ata, unidade_gerenciadora, numero_item, unidade, tipo)
);

CREATE TABLE IF NOT EXISTS dadosabertos_arp_item_unidades (
    numero_ata             TEXT NOT NULL,
    unidade_gerenciadora   TEXT NOT NULL,
    numero_item            TEXT NOT NULL,
    seq                    INTEGER NOT NULL,
    codigo_pdm             TEXT,
    descricao_item         TEXT,
    fornecedor             TEXT,
    quantidade_registrada  NUMERIC(20,4),
    saldo_adesoes          NUMERIC(20,4),
    fonte                  TEXT NOT NULL,
    fonte_url              TEXT NOT NULL,
    raw_json               JSONB NOT NULL,
    coletado_em            TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (numero_ata, unidade_gerenciadora, numero_item, seq)
);

CREATE TABLE IF NOT EXISTS dadosabertos_arp_item_adesoes (
    numero_ata             TEXT NOT NULL,
    unidade_gerenciadora   TEXT NOT NULL,
    numero_item            TEXT NOT NULL,
    seq                    INTEGER NOT NULL,
    fonte                  TEXT NOT NULL,
    fonte_url              TEXT NOT NULL,
    raw_json               JSONB NOT NULL,
    coletado_em            TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (numero_ata, unidade_gerenciadora, numero_item, seq)
);
