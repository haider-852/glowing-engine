-- Core schema for case verification, briefs and the citator.
--
-- Needs Postgres 16+ with the pg_trgm and pgvector extensions.
-- Text values are restricted with CHECK constraints rather than enum types,
-- so adding a value later is a one-line migration.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS vector;

-- Data sources and what we are allowed to do with each -----------------------

CREATE TABLE sources (
    id              smallserial PRIMARY KEY,
    name            text NOT NULL UNIQUE,          -- 'sc_website', 'digital_scr', 'indian_kanoon'
    -- Records with the same origin are not independent witnesses
    -- (a site republishing SC website text has origin 'sc_website').
    origin          text NOT NULL,
    official        boolean NOT NULL,
    terms_url       text,
    may_store_text  boolean NOT NULL DEFAULT false, -- from the signed terms
    may_cache_until interval,                       -- NULL = no limit stated
    notes           text
);

-- Cases ----------------------------------------------------------------------

CREATE TABLE cases (
    id                  bigserial PRIMARY KEY,
    slug                text NOT NULL UNIQUE,      -- 'kesavananda-bharati-1973'
    title               text NOT NULL,
    court               text NOT NULL DEFAULT 'SCI',
    decision_date       date,
    bench_strength      smallint CHECK (bench_strength > 0),
    judges              text[] NOT NULL DEFAULT '{}',
    outcome             text,
    status              text NOT NULL DEFAULT 'unknown' CHECK (status IN (
                            'unknown',
                            'good_law',
                            'good_law_negative_treatment',
                            'under_reconsideration',
                            'partly_overruled',
                            'overruled',
                            'reversed',                 -- set aside in appeal, review or curative
                            'legislatively_overridden'
                        )),
    status_reason       text,
    verification_status text NOT NULL DEFAULT 'could_not_verify' CHECK (verification_status IN (
                            'verified', 'partly_verified', 'could_not_verify'
                        )),
    verified_at         timestamptz,
    -- Victims of sexual offences, children, in-camera matrimonial matters:
    -- names must be masked everywhere this case is shown (Nipun Saxena).
    requires_identity_masking boolean NOT NULL DEFAULT false,
    cited_by_count      integer NOT NULL DEFAULT 0,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    CHECK (verification_status <> 'verified' OR verified_at IS NOT NULL),
    CHECK (bench_strength IS NULL OR cardinality(judges) = 0 OR cardinality(judges) = bench_strength)
);

CREATE INDEX cases_title_trgm ON cases USING gin (lower(title) gin_trgm_ops);

CREATE TABLE case_aliases (
    id          bigserial PRIMARY KEY,
    case_id     bigint NOT NULL REFERENCES cases ON DELETE CASCADE,
    alias       text NOT NULL,
    normalized  text NOT NULL,                     -- app.text.normalize(alias)
    kind        text NOT NULL CHECK (kind IN ('popular', 'formal', 'short', 'variant')),
    -- One alias can belong to several cases ("Puttaswamy"); that is how the
    -- resolver knows to ask which one was meant.
    UNIQUE (case_id, normalized)
);

CREATE INDEX case_aliases_trgm ON case_aliases USING gin (normalized gin_trgm_ops);

CREATE TABLE citations (
    id          bigserial PRIMARY KEY,
    case_id     bigint NOT NULL REFERENCES cases ON DELETE CASCADE,
    canonical   text NOT NULL UNIQUE,              -- app.citations.Citation.canonical
    reporter    text NOT NULL CHECK (reporter IN ('SCC', 'AIR', 'SCR', 'SCALE', 'JT', 'INSC')),
    reporter_key text NOT NULL,                    -- 'SCC', 'SCC (Cri)', 'AIR SC', ...
    year        smallint NOT NULL,
    volume      smallint,
    page        integer NOT NULL,
    source_id   smallint REFERENCES sources,       -- where we got this citation from
    UNIQUE (case_id, reporter_key)
);

-- Retrieved documents --------------------------------------------------------

CREATE TABLE source_documents (
    id              bigserial PRIMARY KEY,
    case_id         bigint NOT NULL REFERENCES cases ON DELETE CASCADE,
    source_id       smallint NOT NULL REFERENCES sources,
    external_id     text,                          -- the source's own id for the judgment
    url             text,
    retrieved_at    timestamptz NOT NULL,
    content_sha256  text NOT NULL,
    raw_object_key  text,                          -- original file in object storage
    text_object_key text,                          -- cleaned text in object storage
    ocr_used        boolean NOT NULL DEFAULT false,
    ocr_quality     real CHECK (ocr_quality BETWEEN 0 AND 1),
    metadata        jsonb NOT NULL DEFAULT '{}',   -- title, date, bench and citations as the source gave them
    UNIQUE (source_id, external_id, content_sha256)
);

CREATE INDEX source_documents_case ON source_documents (case_id);

-- Opinions and paragraphs ----------------------------------------------------

CREATE TABLE opinions (
    id          bigserial PRIMARY KEY,
    case_id     bigint NOT NULL REFERENCES cases ON DELETE CASCADE,
    ordinal     smallint NOT NULL,
    authors     text[] NOT NULL DEFAULT '{}',
    kind        text NOT NULL CHECK (kind IN (
                    'majority', 'plurality', 'concurring', 'dissenting', 'per_curiam', 'summary', 'unknown'
                )),
    UNIQUE (case_id, ordinal)
);

-- Paragraph numbering: many older judgments have no court-assigned numbers,
-- and SCC's numbering is protected editorial work (EBC v. D.B. Modak). So
-- every paragraph gets our own stable id; court_number is filled only when
-- the court's own text numbers the paragraph.
CREATE TABLE paragraphs (
    id              bigserial PRIMARY KEY,
    case_id         bigint NOT NULL REFERENCES cases ON DELETE CASCADE,
    opinion_id      bigint REFERENCES opinions ON DELETE CASCADE,
    document_id     bigint NOT NULL REFERENCES source_documents,
    ordinal         integer NOT NULL,              -- our numbering, 1..n across the judgment
    court_number    text,                          -- '34', '34A'; NULL when the court did not number it
    scr_page        integer,                       -- page in the official SCR report, when known
    text            text NOT NULL,
    embedding       vector(1024),                  -- dimension must match the embedding model
    UNIQUE (case_id, ordinal)
);

CREATE INDEX paragraphs_embedding ON paragraphs USING hnsw (embedding vector_cosine_ops);

-- The citator ----------------------------------------------------------------

CREATE TABLE citing_edges (
    id              bigserial PRIMARY KEY,
    citing_case_id  bigint NOT NULL REFERENCES cases ON DELETE CASCADE,
    cited_case_id   bigint NOT NULL REFERENCES cases ON DELETE CASCADE,
    paragraph_id    bigint REFERENCES paragraphs,  -- where in the citing case the treatment appears
    issue           text,                          -- treatment is per issue; NULL = whole case
    treatment       text NOT NULL CHECK (treatment IN (
                        'followed', 'referred', 'explained', 'distinguished', 'doubted',
                        'referred_to_larger_bench', 'per_incuriam', 'overruled', 'partly_overruled',
                        'reversed'
                    )),
    evidence_quote  text NOT NULL,                 -- the passage that shows the treatment
    distinguished_on text,                         -- for 'distinguished': which facts
    confidence      real NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    model           text NOT NULL,
    prompt_version  text NOT NULL,
    review_status   text NOT NULL DEFAULT 'unreviewed' CHECK (review_status IN (
                        'unreviewed', 'confirmed', 'rejected', 'needs_review'
                    )),
    reviewer        text,
    reviewed_at     timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    CHECK (citing_case_id <> cited_case_id),
    CHECK (review_status IN ('unreviewed', 'needs_review') OR (reviewer IS NOT NULL AND reviewed_at IS NOT NULL))
);

CREATE INDEX citing_edges_cited ON citing_edges (cited_case_id, treatment);
CREATE INDEX citing_edges_citing ON citing_edges (citing_case_id);

-- Changes made outside the courts (e.g. Shah Bano and the 1986 Act).
CREATE TABLE legislative_overrides (
    id              bigserial PRIMARY KEY,
    case_id         bigint NOT NULL REFERENCES cases ON DELETE CASCADE,
    instrument      text NOT NULL,                 -- statute or constitutional amendment
    enacted_on      date,
    effect          text NOT NULL CHECK (effect IN ('nullified', 'modified', 'codified')),
    issue           text,
    note            text,
    evidence_url    text,
    reviewer        text NOT NULL,                 -- curated by hand, always reviewed
    reviewed_at     timestamptz NOT NULL
);

-- Briefs ---------------------------------------------------------------------

CREATE TABLE briefs (
    id              bigserial PRIMARY KEY,
    case_id         bigint NOT NULL REFERENCES cases ON DELETE CASCADE,
    depth           text NOT NULL CHECK (depth IN ('quick', 'full', 'moot', 'plain')),
    version         integer NOT NULL,
    sections        jsonb NOT NULL,                -- facts, issues, arguments, holding, ratio, obiter, opinions
    claim_refs      jsonb NOT NULL,                -- each claim -> paragraph ids it relies on
    model           text NOT NULL,
    prompt_version  text NOT NULL,
    document_ids    bigint[] NOT NULL,             -- the source_documents the brief was written from
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (case_id, depth, version)
);

-- Error reports become test cases --------------------------------------------

CREATE TABLE error_reports (
    id              bigserial PRIMARY KEY,
    case_id         bigint REFERENCES cases ON DELETE SET NULL,
    brief_id        bigint REFERENCES briefs ON DELETE SET NULL,
    query           text,
    body            text NOT NULL,
    status          text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'confirmed', 'rejected', 'fixed')),
    added_to_test_set boolean NOT NULL DEFAULT false,
    created_at      timestamptz NOT NULL DEFAULT now()
);

COMMIT;
