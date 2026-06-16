-- Facility Trust Desk (Track 1) — Lakebase schema (in the `commons` instance, db databricks_postgres).
-- Source: databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.facilities (10,088 rows).
-- Timestamps are epoch seconds (bigint).

-- The facility records. Key columns typed for the app + extraction; the full row kept in `raw`.
CREATE TABLE IF NOT EXISTS facilities (
    id                TEXT PRIMARY KEY,        -- unique_id
    name              TEXT,
    organization_type TEXT,                    -- organization_type
    facility_type     TEXT,                    -- facilityTypeId (clinic/hospital/...)
    operator_type     TEXT,                    -- operatorTypeId (private/public/...)
    city              TEXT,                    -- address_city
    state             TEXT,                    -- address_stateOrRegion
    postcode          TEXT,                    -- address_zipOrPostcode
    latitude          DOUBLE PRECISION,
    longitude         DOUBLE PRECISION,
    description       TEXT,                    -- evidence (100%)
    specialties       TEXT,                    -- evidence: JSON array of strings
    procedure         TEXT,                    -- evidence: JSON array
    equipment         TEXT,                    -- evidence: JSON array
    capability        TEXT,                    -- evidence: JSON array (sparse)
    number_doctors    TEXT,
    capacity          TEXT,
    year_established  TEXT,
    websites          TEXT,
    official_website  TEXT,
    source_urls       TEXT,                    -- JSON array of source links (for citations)
    source            TEXT,
    phone             TEXT,
    email             TEXT,
    raw               JSONB                    -- full 51-column row, verbatim
);
CREATE INDEX IF NOT EXISTS ix_fac_state ON facilities (state);
CREATE INDEX IF NOT EXISTS ix_fac_city  ON facilities (city);
CREATE INDEX IF NOT EXISTS ix_fac_type  ON facilities (facility_type);

-- Precomputed trust signals: one row per (facility, capability) — evidence-attached, uncertainty-aware.
CREATE TABLE IF NOT EXISTS trust_signals (
    id            TEXT PRIMARY KEY,
    facility_id   TEXT NOT NULL REFERENCES facilities(id),
    capability    TEXT NOT NULL,               -- icu|maternity|emergency|oncology|trauma|nicu
    signal        TEXT NOT NULL,               -- strong | partial | weak | none
    confidence    DOUBLE PRECISION,            -- 0..1, shown honestly
    evidence      JSONB,                       -- [{field, snippet}] EXACT cited source text
    rationale     TEXT,                        -- one-line why
    model         TEXT,                        -- which model produced it (provenance)
    created_at    BIGINT,
    UNIQUE (facility_id, capability)
);
CREATE INDEX IF NOT EXISTS ix_ts_cap_signal ON trust_signals (capability, signal);
CREATE INDEX IF NOT EXISTS ix_ts_facility   ON trust_signals (facility_id);

-- NFHS-5 demand-side context, aggregated to state (from district fact sheets).
-- Lets Track 2 turn "where is there no supply" into "where is the high-RISK shortfall"
-- (low trusted supply + high health burden / low coverage). Values are percentages.
CREATE TABLE IF NOT EXISTS nfhs_state (
    state                 TEXT PRIMARY KEY,
    institutional_birth   DOUBLE PRECISION,   -- % births in a facility (low = unmet maternity need)
    anc4                  DOUBLE PRECISION,   -- % mothers with >=4 antenatal visits
    csection              DOUBLE PRECISION,   -- % C-section
    insurance             DOUBLE PRECISION,   -- % households with health insurance (low = vulnerable)
    stunting              DOUBLE PRECISION,   -- % under-5 stunted (child health burden)
    n_districts           INTEGER
);

-- Clinical service-line classification + capacity per facility (from classify_facilities.py).
-- The data-readiness layer: which of 7 categories a provider covers (specialties + procedures),
-- bed capacity (total + per-category where stated), and completeness flags.
CREATE TABLE IF NOT EXISTS facility_services (
    facility_id       TEXT PRIMARY KEY,
    facility_type     TEXT,
    city              TEXT,
    state             TEXT,
    postcode          TEXT,
    total_beds        INTEGER,
    n_doctors         INTEGER,
    n_categories      INTEGER,
    n_sources         INTEGER,      -- corroborating source URLs (cardinality)
    services          JSONB,        -- {category: {specialties, procedures, beds, offered}}
    cap_specialists   JSONB,        -- {capability: n_relevant_specialists} — the trust cross-check
    missing_beds      BOOLEAN,      -- inpatient facility with no stated bed count
    missing_specialty BOOLEAN       -- a provider with no specialty attached
);
CREATE INDEX IF NOT EXISTS ix_fs_state ON facility_services (state);

-- Append-only user actions ("persist user actions"): overrides, notes, shortlists, decisions.
CREATE TABLE IF NOT EXISTS reviews (
    id            TEXT PRIMARY KEY,
    created_at    BIGINT NOT NULL,
    user_id       TEXT,
    facility_id   TEXT,
    capability    TEXT,                        -- null for facility-level notes
    action        TEXT NOT NULL,               -- override | note | shortlist | unshortlist | decision
    new_signal    TEXT,                        -- for action=override
    body          TEXT,                        -- note / decision text
    shortlist     TEXT                         -- shortlist name
);
CREATE INDEX IF NOT EXISTS ix_rev_facility ON reviews (facility_id);
CREATE INDEX IF NOT EXISTS ix_rev_created  ON reviews (created_at DESC);
