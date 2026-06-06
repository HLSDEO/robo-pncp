-- =========================================================================
-- Schema do Robo PNCP
-- Cada tabela carrega colunas de procedência:
--   fonte       -> identificador curto da origem (ex: 'pncp_search')
--   fonte_url   -> URL completa de onde o registro foi obtido
--   raw_json    -> payload bruto retornado pela API
--   coletado_em -> timestamp da coleta
-- Tabelas distintas por endpoint (sem mesclar dados de fontes diferentes).
-- =========================================================================

CREATE SCHEMA IF NOT EXISTS pncp;
CREATE SCHEMA IF NOT EXISTS comprasnet;
CREATE SCHEMA IF NOT EXISTS dadosabertos;
CREATE SCHEMA IF NOT EXISTS meta;

-- ---------------------------------------------------------------------
-- Metadados de coleta
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS meta.unidades_pf (
    sigla         TEXT PRIMARY KEY,
    codigo_unidade TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS meta.execucao (
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
CREATE TABLE IF NOT EXISTS pncp.editais (
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
CREATE INDEX IF NOT EXISTS idx_editais_unidade  ON pncp.editais (unidade_codigo);
CREATE INDEX IF NOT EXISTS idx_editais_orgao    ON pncp.editais (orgao_cnpj);
CREATE INDEX IF NOT EXISTS idx_editais_ano_seq  ON pncp.editais (orgao_cnpj, ano, numero_sequencial);

-- /api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq}/itens
CREATE TABLE IF NOT EXISTS pncp.edital_itens (
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
CREATE TABLE IF NOT EXISTS pncp.edital_item_resultados (
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
CREATE TABLE IF NOT EXISTS pncp.atas (
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
CREATE INDEX IF NOT EXISTS idx_atas_compra ON pncp.atas (numero_controle_pncp_compra);

-- /api/pncp/v1/orgaos/{cnpj}/contratos/contratacao/{ano}/{seq}
CREATE TABLE IF NOT EXISTS pncp.contratos (
    numero_controle_pncp          TEXT PRIMARY KEY,
    numero_controle_pncp_compra   TEXT,
    ano_contrato                  INTEGER,
    numero_contrato_empenho       TEXT,
    sequencial_contrato           INTEGER,
    tipo_contrato_id              INTEGER,
    tipo_contrato_nome            TEXT,
    orgao_cnpj                    TEXT,
    orgao_razao_social            TEXT,
    orgao_esfera_id               TEXT,
    orgao_poder_id                TEXT,
    unidade_codigo                TEXT,
    unidade_nome                  TEXT,
    ni_fornecedor                 TEXT,
    tipo_pessoa                   TEXT,
    nome_razao_social_fornecedor  TEXT,
    codigo_pais_fornecedor        TEXT,
    categoria_processo_id         INTEGER,
    categoria_processo_nome       TEXT,
    processo                      TEXT,
    objeto_contrato               TEXT,
    valor_inicial                 NUMERIC(20,4),
    valor_global                  NUMERIC(20,4),
    valor_parcela                 NUMERIC(20,4),
    numero_parcelas               INTEGER,
    data_assinatura               DATE,
    data_vigencia_inicio          DATE,
    data_vigencia_fim             DATE,
    data_publicacao_pncp          TIMESTAMPTZ,
    data_atualizacao              TIMESTAMPTZ,
    data_atualizacao_global       TIMESTAMPTZ,
    fonte                         TEXT NOT NULL,
    fonte_url                     TEXT NOT NULL,
    raw_json                      JSONB NOT NULL,
    coletado_em                   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_contratos_compra ON pncp.contratos (numero_controle_pncp_compra);

-- =========================================================================
-- Contratos.comprasnet.gov.br
-- =========================================================================

CREATE TABLE IF NOT EXISTS comprasnet.contratos (
    id                    BIGINT PRIMARY KEY,
    numero                TEXT,
    numero_norm           TEXT,
    receita_despesa       TEXT,
    situacao              TEXT,
    categoria             TEXT,
    subcategoria          TEXT,
    tipo                  TEXT,
    codigo_tipo           TEXT,
    subtipo               TEXT,
    prorrogavel           TEXT,
    processo              TEXT,
    objeto                TEXT,
    amparo_legal          TEXT,
    informacao_complementar TEXT,
    codigo_modalidade     TEXT,
    modalidade            TEXT,
    unidade_compra        TEXT,
    licitacao_numero      TEXT,
    sistema_origem_licitacao TEXT,
    orgao_origem_codigo   TEXT,
    orgao_origem_nome     TEXT,
    ug_origem_codigo      TEXT,
    ug_origem_nome        TEXT,
    orgao_codigo          TEXT,
    orgao_nome            TEXT,
    ug_codigo             TEXT,
    ug_nome               TEXT,
    fornecedor_tipo       TEXT,
    fornecedor_cnpj_cpf   TEXT,
    fornecedor_nome       TEXT,
    data_assinatura       DATE,
    data_publicacao       DATE,
    data_proposta_comercial DATE,
    vigencia_inicio       DATE,
    vigencia_fim          DATE,
    valor_inicial         NUMERIC(20,4),
    valor_global          NUMERIC(20,4),
    valor_parcela         NUMERIC(20,4),
    valor_acumulado       NUMERIC(20,4),
    num_parcelas          INTEGER,
    fonte                 TEXT NOT NULL,
    fonte_url             TEXT NOT NULL,
    raw_json              JSONB NOT NULL,
    coletado_em           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_compras_contratos_ug ON comprasnet.contratos (ug_origem_codigo);
CREATE INDEX IF NOT EXISTS idx_compras_contratos_numero ON comprasnet.contratos (numero_norm);

-- Sub-rotas dos contratos (uma tabela por rota - preservando origem)
-- Cada linha guarda payload bruto da rota correspondente.
CREATE TABLE IF NOT EXISTS comprasnet.contrato_subrota (
    contrato_id   BIGINT NOT NULL,
    subrota       TEXT   NOT NULL,        -- 'historico','empenhos','cronograma','garantias','itens','prepostos','responsaveis','despesas_acessorias','faturas','ocorrencias','terceirizados','arquivos'
    item_id       TEXT   NOT NULL,        -- id do item ou hash; quando a API nao da id, usamos posicao
    fonte         TEXT   NOT NULL,
    fonte_url     TEXT   NOT NULL,
    raw_json      JSONB  NOT NULL,
    coletado_em   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (contrato_id, subrota, item_id)
);
CREATE INDEX IF NOT EXISTS idx_contrato_subrota_rota ON comprasnet.contrato_subrota (subrota);

-- =========================================================================
-- Dados Abertos Comprasgov - dadosabertos.compras.gov.br
-- =========================================================================

-- Hierarquia de Material
CREATE TABLE IF NOT EXISTS dadosabertos.material_grupo (
    codigo_grupo  TEXT PRIMARY KEY,
    nome_grupo    TEXT,
    fonte         TEXT NOT NULL,
    fonte_url     TEXT NOT NULL,
    raw_json      JSONB NOT NULL,
    coletado_em   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dadosabertos.material_classe (
    codigo_classe TEXT PRIMARY KEY,
    codigo_grupo  TEXT,
    nome_classe   TEXT,
    fonte         TEXT NOT NULL,
    fonte_url     TEXT NOT NULL,
    raw_json      JSONB NOT NULL,
    coletado_em   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dadosabertos.material_pdm (
    codigo_pdm    TEXT PRIMARY KEY,
    codigo_classe TEXT,
    nome_pdm      TEXT,
    fonte         TEXT NOT NULL,
    fonte_url     TEXT NOT NULL,
    raw_json      JSONB NOT NULL,
    coletado_em   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dadosabertos.material (
    codigo_material TEXT PRIMARY KEY,
    codigo_pdm      TEXT,
    codigo_classe   TEXT,
    codigo_grupo    TEXT,
    nome_material   TEXT,
    fonte           TEXT NOT NULL,
    fonte_url       TEXT NOT NULL,
    raw_json        JSONB NOT NULL,
    coletado_em     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Hierarquia de Servico
CREATE TABLE IF NOT EXISTS dadosabertos.servico_grupo (
    codigo_grupo  TEXT PRIMARY KEY,
    nome_grupo    TEXT,
    fonte         TEXT NOT NULL,
    fonte_url     TEXT NOT NULL,
    raw_json      JSONB NOT NULL,
    coletado_em   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dadosabertos.servico_classe (
    codigo_classe TEXT PRIMARY KEY,
    codigo_grupo  TEXT,
    nome_classe   TEXT,
    fonte         TEXT NOT NULL,
    fonte_url     TEXT NOT NULL,
    raw_json      JSONB NOT NULL,
    coletado_em   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dadosabertos.servico (
    codigo_servico TEXT PRIMARY KEY,
    codigo_classe  TEXT,
    codigo_grupo   TEXT,
    nome_servico   TEXT,
    fonte          TEXT NOT NULL,
    fonte_url      TEXT NOT NULL,
    raw_json       JSONB NOT NULL,
    coletado_em    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ARP (Ata de Registro de Precos) - dados abertos
CREATE TABLE IF NOT EXISTS dadosabertos.arp (
    numero_controle_pncp_ata  TEXT PRIMARY KEY,
    numero_controle_pncp_compra TEXT,
    orgao_cnpj                TEXT,
    unidade_codigo            TEXT,
    numero_ata                TEXT,
    ano_ata                   INTEGER,
    sequencial_ata            INTEGER,
    data_assinatura           DATE,
    data_vigencia_inicio      DATE,
    data_vigencia_fim         DATE,
    cancelado                 BOOLEAN,
    fonte                     TEXT NOT NULL,
    fonte_url                 TEXT NOT NULL,
    raw_json                  JSONB NOT NULL,
    coletado_em               TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_arp_compra ON dadosabertos.arp (numero_controle_pncp_compra);

CREATE TABLE IF NOT EXISTS dadosabertos.arp_itens (
    numero_controle_pncp_ata TEXT NOT NULL,
    numero_item              INTEGER NOT NULL,
    descricao                TEXT,
    material_ou_servico      TEXT,
    quantidade_registrada    NUMERIC(20,4),
    valor_unitario_registrado NUMERIC(20,4),
    unidade_medida           TEXT,
    ni_fornecedor            TEXT,
    nome_razao_social        TEXT,
    fonte                    TEXT NOT NULL,
    fonte_url                TEXT NOT NULL,
    raw_json                 JSONB NOT NULL,
    coletado_em              TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (numero_controle_pncp_ata, numero_item)
);

CREATE TABLE IF NOT EXISTS dadosabertos.arp_item_empenhos (
    numero_controle_pncp_ata TEXT NOT NULL,
    numero_item              INTEGER NOT NULL,
    numero_empenho           TEXT NOT NULL,
    ug_empenho               TEXT,
    data_empenho             DATE,
    valor_empenhado          NUMERIC(20,4),
    quantidade_empenhada     NUMERIC(20,4),
    fonte                    TEXT NOT NULL,
    fonte_url                TEXT NOT NULL,
    raw_json                 JSONB NOT NULL,
    coletado_em              TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (numero_controle_pncp_ata, numero_item, numero_empenho)
);

CREATE TABLE IF NOT EXISTS dadosabertos.arp_item_adesoes (
    numero_controle_pncp_ata TEXT NOT NULL,
    numero_item              INTEGER NOT NULL,
    sequencial_adesao        INTEGER NOT NULL,
    cnpj_aderente            TEXT,
    nome_aderente            TEXT,
    quantidade_aderida       NUMERIC(20,4),
    valor_aderido            NUMERIC(20,4),
    data_adesao              DATE,
    fonte                    TEXT NOT NULL,
    fonte_url                TEXT NOT NULL,
    raw_json                 JSONB NOT NULL,
    coletado_em              TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (numero_controle_pncp_ata, numero_item, sequencial_adesao)
);
