-- =============================================================================
-- Speaker Program Impact / ROI — Database Schema
-- Three logical zones: bronze (raw), silver (conformed), gold (analytics)
--
-- Engine: DuckDB (PostgreSQL-compatible SQL; portable to Postgres with
-- minimal changes — only COPY syntax differs).
-- =============================================================================

-- ============================================================
-- BRONZE SCHEMA — raw source tables, loaded as-is from CSVs
-- ============================================================
CREATE SCHEMA IF NOT EXISTS bronze;

CREATE TABLE bronze.hcp_master (
    hcp_id          VARCHAR(12) PRIMARY KEY,
    specialty       VARCHAR(30) NOT NULL,
    region          VARCHAR(30) NOT NULL,
    segment         VARCHAR(10) NOT NULL,
    active_flag     INTEGER     NOT NULL CHECK (active_flag IN (0, 1))
);

CREATE TABLE bronze.events (
    event_id   VARCHAR(10)  PRIMARY KEY,
    date       DATE         NOT NULL,
    topic      VARCHAR(60)  NOT NULL,
    format     VARCHAR(15)  NOT NULL,
    speaker    VARCHAR(15)  NOT NULL,
    status     VARCHAR(12)  NOT NULL CHECK (status IN ('Completed','Cancelled','Planned'))
);

CREATE TABLE bronze.event_invitations (
    event_id        VARCHAR(10)  NOT NULL,
    hcp_id          VARCHAR(12)  NOT NULL,
    invited_at      DATE         NOT NULL,
    channel         VARCHAR(10)  NOT NULL,
    eligible_reason VARCHAR(40)  NOT NULL,
    PRIMARY KEY (event_id, hcp_id)
);

-- No PK on bronze attendance — intentional ~1% duplicate sign-ins
CREATE TABLE bronze.event_attendance (
    event_id          VARCHAR(10)  NOT NULL,
    hcp_id            VARCHAR(12)  NOT NULL,
    registered        INTEGER      NOT NULL CHECK (registered IN (0, 1)),
    verified_attended INTEGER      NOT NULL CHECK (verified_attended IN (0, 1)),
    duration          INTEGER      NOT NULL,
    engagement        INTEGER      NOT NULL CHECK (engagement BETWEEN 0 AND 100)
);

CREATE TABLE bronze.hcp_rx_monthly (
    hcp_id         VARCHAR(12) NOT NULL,
    month          VARCHAR(7)  NOT NULL,
    product        VARCHAR(15) NOT NULL,
    nrx            INTEGER     NOT NULL CHECK (nrx >= 0),
    trx            INTEGER     NOT NULL CHECK (trx >= 0),
    competitor_trx INTEGER     NOT NULL CHECK (competitor_trx >= 0)
);

CREATE TABLE bronze.marketing_activity (
    hcp_id       VARCHAR(12) NOT NULL,
    date         DATE        NOT NULL,
    rep_calls    INTEGER     NOT NULL CHECK (rep_calls >= 0),
    emails       INTEGER     NOT NULL CHECK (emails >= 0),
    samples      INTEGER     NOT NULL CHECK (samples >= 0),
    other_events INTEGER     NOT NULL CHECK (other_events >= 0),
    PRIMARY KEY (hcp_id, date)
);

CREATE TABLE bronze.event_cost (
    event_id   VARCHAR(10)   PRIMARY KEY,
    honorarium NUMERIC(10,2) NOT NULL CHECK (honorarium >= 0),
    venue      NUMERIC(10,2) NOT NULL CHECK (venue >= 0),
    meal       NUMERIC(10,2) NOT NULL CHECK (meal >= 0),
    travel     NUMERIC(10,2) NOT NULL CHECK (travel >= 0),
    agency     NUMERIC(10,2) NOT NULL CHECK (agency >= 0),
    total      NUMERIC(10,2) NOT NULL CHECK (total >= 0)
);

CREATE TABLE bronze.market_factors (
    region           VARCHAR(30) NOT NULL,
    month            VARCHAR(7)  NOT NULL,
    access           NUMERIC(6,4) NOT NULL,
    seasonality      NUMERIC(6,4) NOT NULL,
    competitor_index NUMERIC(6,4) NOT NULL,
    PRIMARY KEY (region, month)
);

CREATE TABLE bronze.identity_crosswalk (
    master_hcp_id    VARCHAR(12)  PRIMARY KEY,
    crm_hcp_id       VARCHAR(20)  NOT NULL,
    event_hcp_id     VARCHAR(20),             -- NULL for ~2% (unresolved)
    rx_vendor_hcp_id VARCHAR(20),             -- NULL for ~3% (unresolved)
    match_status     VARCHAR(10)  NOT NULL CHECK (match_status IN ('verified','review'))
);

CREATE TABLE bronze.business_assumptions (
    product                            VARCHAR(15)    NOT NULL,
    scenario                           VARCHAR(15)    NOT NULL CHECK (scenario IN ('Conservative','Base','Optimistic')),
    expected_fills_per_new_rx          NUMERIC(6,2)   NOT NULL,
    net_contribution_per_fill          NUMERIC(10,2)  NOT NULL,
    net_contribution_per_incremental_nrx NUMERIC(12,2) NOT NULL,
    PRIMARY KEY (product, scenario)
);

CREATE TABLE bronze.ground_truth (
    event_id              VARCHAR(10)    NOT NULL,
    hcp_id                VARCHAR(12)    NOT NULL,
    true_event_effect_nrx NUMERIC(12,4)  NOT NULL,
    true_event_effect_trx NUMERIC(12,4)  NOT NULL,
    PRIMARY KEY (event_id, hcp_id)
);

-- ============================================================
-- SILVER SCHEMA — conformed, deduplicated, identity-resolved
-- ============================================================
CREATE SCHEMA IF NOT EXISTS silver;

CREATE TABLE silver.hcp_master (
    hcp_id      VARCHAR(12) PRIMARY KEY,
    specialty   VARCHAR(30) NOT NULL,
    region      VARCHAR(30) NOT NULL,
    segment     VARCHAR(10) NOT NULL,
    active_flag INTEGER     NOT NULL CHECK (active_flag IN (0, 1))
);

CREATE TABLE silver.events (
    event_id VARCHAR(10)  PRIMARY KEY,
    date     DATE         NOT NULL,
    topic    VARCHAR(60)  NOT NULL,
    format   VARCHAR(15)  NOT NULL,
    speaker  VARCHAR(15)  NOT NULL,
    status   VARCHAR(12)  NOT NULL CHECK (status IN ('Completed','Cancelled','Planned'))
);

CREATE TABLE silver.event_invitations (
    event_id        VARCHAR(10) NOT NULL REFERENCES silver.events(event_id),
    hcp_id          VARCHAR(12) NOT NULL REFERENCES silver.hcp_master(hcp_id),
    invited_at      DATE        NOT NULL,
    channel         VARCHAR(10) NOT NULL,
    eligible_reason VARCHAR(40) NOT NULL,
    PRIMARY KEY (event_id, hcp_id)
);

CREATE TABLE silver.event_attendance (
    event_id          VARCHAR(10) NOT NULL REFERENCES silver.events(event_id),
    hcp_id            VARCHAR(12) NOT NULL REFERENCES silver.hcp_master(hcp_id),
    registered        INTEGER     NOT NULL CHECK (registered IN (0, 1)),
    verified_attended INTEGER     NOT NULL CHECK (verified_attended IN (0, 1)),
    duration          INTEGER     NOT NULL,
    engagement        INTEGER     NOT NULL CHECK (engagement BETWEEN 0 AND 100),
    PRIMARY KEY (event_id, hcp_id)
);

CREATE TABLE silver.hcp_rx_monthly (
    hcp_id         VARCHAR(12) NOT NULL REFERENCES silver.hcp_master(hcp_id),
    month          VARCHAR(7)  NOT NULL,
    product        VARCHAR(15) NOT NULL,
    nrx            INTEGER     NOT NULL CHECK (nrx >= 0),
    trx            INTEGER     NOT NULL CHECK (trx >= 0),
    competitor_trx INTEGER     NOT NULL CHECK (competitor_trx >= 0),
    PRIMARY KEY (hcp_id, month, product)
);

CREATE TABLE silver.marketing_activity (
    hcp_id       VARCHAR(12) NOT NULL REFERENCES silver.hcp_master(hcp_id),
    date         DATE        NOT NULL,
    rep_calls    INTEGER     NOT NULL CHECK (rep_calls >= 0),
    emails       INTEGER     NOT NULL CHECK (emails >= 0),
    samples      INTEGER     NOT NULL CHECK (samples >= 0),
    other_events INTEGER     NOT NULL CHECK (other_events >= 0),
    PRIMARY KEY (hcp_id, date)
);

CREATE TABLE silver.event_cost (
    event_id            VARCHAR(10)   PRIMARY KEY REFERENCES silver.events(event_id),
    honorarium          NUMERIC(10,2) NOT NULL CHECK (honorarium >= 0),
    venue               NUMERIC(10,2) NOT NULL CHECK (venue >= 0),
    meal                NUMERIC(10,2) NOT NULL CHECK (meal >= 0),
    travel              NUMERIC(10,2) NOT NULL CHECK (travel >= 0),
    agency              NUMERIC(10,2) NOT NULL CHECK (agency >= 0),
    total               NUMERIC(10,2) NOT NULL CHECK (total >= 0),
    finance_review_flag INTEGER       NOT NULL DEFAULT 0 CHECK (finance_review_flag IN (0, 1))
);

CREATE TABLE silver.market_factors (
    region           VARCHAR(30)  NOT NULL,
    month            VARCHAR(7)   NOT NULL,
    access           NUMERIC(6,4) NOT NULL,
    seasonality      NUMERIC(6,4) NOT NULL,
    competitor_index NUMERIC(6,4) NOT NULL,
    PRIMARY KEY (region, month)
);

CREATE TABLE silver.identity_crosswalk (
    master_hcp_id    VARCHAR(12) PRIMARY KEY REFERENCES silver.hcp_master(hcp_id),
    crm_hcp_id       VARCHAR(20) NOT NULL,
    event_hcp_id     VARCHAR(20),
    rx_vendor_hcp_id VARCHAR(20),
    match_status     VARCHAR(10) NOT NULL CHECK (match_status IN ('verified','review'))
);

CREATE TABLE silver.business_assumptions (
    product                            VARCHAR(15)    NOT NULL,
    scenario                           VARCHAR(15)    NOT NULL CHECK (scenario IN ('Conservative','Base','Optimistic')),
    expected_fills_per_new_rx          NUMERIC(6,2)   NOT NULL,
    net_contribution_per_fill          NUMERIC(10,2)  NOT NULL,
    net_contribution_per_incremental_nrx NUMERIC(12,2) NOT NULL,
    PRIMARY KEY (product, scenario)
);

-- ============================================================
-- GOLD SCHEMA — analytics-ready tables
-- ============================================================
CREATE SCHEMA IF NOT EXISTS gold;

-- NOTE: DuckDB does not support cross-schema foreign keys.
-- In PostgreSQL, add: REFERENCES silver.hcp_master(hcp_id) and silver.events(event_id).
CREATE TABLE gold.eligibility_table (
    master_hcp_id    VARCHAR(12)  NOT NULL,
    event_id         VARCHAR(10)  NOT NULL,
    event_date       DATE         NOT NULL,
    "group"          VARCHAR(25)  NOT NULL CHECK ("group" IN ('treatment','control_candidate','excluded')),
    exclusion_reason VARCHAR(50),
    contaminated     BOOLEAN      NOT NULL,
    PRIMARY KEY (master_hcp_id, event_id)
);

CREATE TABLE gold.eligibility_summary (
    event_id          VARCHAR(10) PRIMARY KEY,
    event_date        VARCHAR(10),
    treatment         INTEGER NOT NULL,
    control_candidate INTEGER NOT NULL,
    excluded          INTEGER NOT NULL,
    total_invited     INTEGER NOT NULL
);
