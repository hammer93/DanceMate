-- DanceMate v0.88.0 - Public Directory Tabs, Communities and Notice Board.
--
-- The first screen grows four tabs next to its events: 장소 (the existing
-- venues), 동호회, 정보원 (the existing sources) and 게시판. Two of those
-- need tables of their own:
--
-- * communities - canonical master data for a dance club/society, tied to
--   genres and venues many-to-many. Operator-entered only: nothing is seeded,
--   because a community is a real group of people and inventing one would be
--   exactly the kind of made-up record this product refuses to show.
-- * boards / board_posts - a notice board. One board exists today (NOTICE,
--   seeded below), but the shape is the general one: a post belongs to a
--   board, a board has a type and a write policy, and a post records what
--   kind of author wrote it, so more boards and a member login can arrive
--   later without reshaping anything. Nothing here builds either of those.
--
-- Genre links follow 028_venue_genres.sql: the owning row's side cascades
-- (a link has no meaning without its community/post), the genre side does
-- not (a genre still in use cannot be deleted out from under them -
-- master_data.genre_usage() counts these too and says so first).
-- community_venues cascades on the venue side as well: a deleted venue simply
-- stops being one of the community's places, as venue_genres already does.

CREATE TABLE IF NOT EXISTS communities (
    community_id  BIGSERIAL PRIMARY KEY,
    name          TEXT NOT NULL,
    region_id     BIGINT REFERENCES regions (region_id),
    -- Shown on the public page.
    description   TEXT,
    homepage_url  TEXT,
    -- The operator's own note. Never shown on the public page.
    notes         TEXT,
    enabled       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT communities_name_check CHECK (btrim(name) <> '')
);

-- One community per name, however it is capitalised or padded.
CREATE UNIQUE INDEX IF NOT EXISTS communities_name_unique
    ON communities (lower(btrim(name)));

CREATE TABLE IF NOT EXISTS community_genres (
    community_id BIGINT NOT NULL REFERENCES communities (community_id) ON DELETE CASCADE,
    genre_id     BIGINT NOT NULL REFERENCES genres (genre_id),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (community_id, genre_id)
);

CREATE INDEX IF NOT EXISTS community_genres_genre_idx ON community_genres (genre_id);

CREATE TABLE IF NOT EXISTS community_venues (
    community_id BIGINT NOT NULL REFERENCES communities (community_id) ON DELETE CASCADE,
    venue_id     BIGINT NOT NULL REFERENCES venues (venue_id) ON DELETE CASCADE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (community_id, venue_id)
);

CREATE INDEX IF NOT EXISTS community_venues_venue_idx ON community_venues (venue_id);

CREATE TABLE IF NOT EXISTS boards (
    board_id      BIGSERIAL PRIMARY KEY,
    code          TEXT NOT NULL,
    name          TEXT NOT NULL,
    board_type    TEXT NOT NULL,
    -- Who may write. ADMIN is the only writer today; MEMBER is reserved for
    -- the future login and nothing grants it yet.
    write_access  TEXT NOT NULL DEFAULT 'ADMIN',
    enabled       BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order    INTEGER NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT boards_code_check CHECK (code ~ '^[A-Z][A-Z0-9_]{0,31}$'),
    -- Extended by a later migration when a second kind of board exists, the
    -- same drop-and-recreate shape master_data_actions' checks already use.
    CONSTRAINT boards_type_check CHECK (board_type IN ('NOTICE')),
    CONSTRAINT boards_write_access_check CHECK (write_access IN ('ADMIN', 'MEMBER'))
);

CREATE UNIQUE INDEX IF NOT EXISTS boards_code_unique ON boards (code);

INSERT INTO boards (code, name, board_type, write_access, sort_order)
VALUES ('NOTICE', '공지사항', 'NOTICE', 'ADMIN', 0)
ON CONFLICT (code) DO NOTHING;

CREATE TABLE IF NOT EXISTS board_posts (
    post_id         BIGSERIAL PRIMARY KEY,
    board_id        BIGINT NOT NULL REFERENCES boards (board_id),
    title           TEXT NOT NULL,
    -- Plain text. Rendered escaped, line breaks kept, bare http(s) links
    -- linked - never interpreted as HTML.
    body            TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'DRAFT',
    pinned          BOOLEAN NOT NULL DEFAULT FALSE,
    -- ADMIN: written in the console, author_name is the operator's login for
    -- the audit trail and is never shown publicly. MEMBER/author_user_id
    -- are for the future login: nothing sets them yet, and there is no users
    -- table for a foreign key to point at.
    author_kind     TEXT NOT NULL DEFAULT 'ADMIN',
    author_name     TEXT,
    author_user_id  BIGINT,
    published_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT board_posts_title_check CHECK (btrim(title) <> ''),
    CONSTRAINT board_posts_status_check CHECK (status IN ('DRAFT', 'PUBLISHED', 'HIDDEN')),
    CONSTRAINT board_posts_author_kind_check CHECK (author_kind IN ('ADMIN', 'MEMBER')),
    CONSTRAINT board_posts_published_at_check
        CHECK (status <> 'PUBLISHED' OR published_at IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS board_posts_listing_idx
    ON board_posts (board_id, status, pinned DESC, published_at DESC);

-- A post with no rows here is a global notice: it is for every genre.
CREATE TABLE IF NOT EXISTS board_post_genres (
    post_id    BIGINT NOT NULL REFERENCES board_posts (post_id) ON DELETE CASCADE,
    genre_id   BIGINT NOT NULL REFERENCES genres (genre_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (post_id, genre_id)
);

CREATE INDEX IF NOT EXISTS board_post_genres_genre_idx ON board_post_genres (genre_id);

-- The audit trail every master-data edit already writes to learns the two
-- new kinds of row and the one new verb (a row created in the console).
-- Same drop-and-recreate shape as 018/020/028/031.
ALTER TABLE master_data_actions
    DROP CONSTRAINT IF EXISTS master_data_actions_entity_check;
ALTER TABLE master_data_actions
    ADD CONSTRAINT master_data_actions_entity_check
    CHECK (entity_type IN (
        'GENRE', 'REGION', 'VENUE', 'ORGANIZER', 'SOURCE',
        'COMMUNITY', 'BOARD_POST'
    ));

ALTER TABLE master_data_actions
    DROP CONSTRAINT IF EXISTS master_data_actions_action_check;
ALTER TABLE master_data_actions
    ADD CONSTRAINT master_data_actions_action_check
    CHECK (action IN (
        'EDIT', 'ENABLE', 'DISABLE', 'ALIAS_ADD', 'ALIAS_REMOVE',
        'VENUE_CSV_IMPORT', 'SOURCE_CSV_IMPORT',
        'GENRE_ADD', 'GENRE_REMOVE',
        'DELETE',
        -- A community or a notice created in the console (v0.88.0).
        'CREATE'
    ));
