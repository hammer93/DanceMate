-- v0.82.4 Regional Coverage - add every region the current live Tango
-- sources (SRC-W-002/003/004/005) actually reference and the region master
-- was still missing (confirmed against real source_items/events, not added
-- to round out a list): the address-parsing table in
-- runtime/venue_resolution.py's _REGION_BY_ADMIN already maps all of these
-- Korean province/metro names to a code - it has simply had nowhere to
-- resolve them to since the master only ever seeded KR/KR-SEOUL/KR-BUSAN
-- (002_master_data.sql) plus KR-DAEJEON (added later, live, by an
-- operator). No code change is required for these seven to start
-- resolving through the existing suggested_region_id() path once an
-- operator links a venue.
--
--   경남 (Gyeongnam)  - Jinju ("진주시 평거로...") and Changwon
--                       ("경남 창원시 마산합포구...") milongas, Miltang
--   충북 (Chungbuk)   - Cheongju ("청주시 서원구...") milonga, Miltang
--   경북 (Gyeongbuk)  - Pohang ("포항시 남구...") milonga, Miltang
--   울산 (Ulsan)      - an Ulsan milonga, Miltang
--   대구 (Daegu)      - a Daegu milonga ("대구 북구 침산로..."), Miltang
--   제주 (Jeju)       - a Jeju milonga ("제주특별자치도 서귀포시..."), Miltang
--   경기 (Gyeonggi)   - a Bundang/Seongnam milonga, Miltang
--
-- Four cities get their own row rather than only their enclosing province,
-- because their real source addresses never actually carry the province
-- name at all ("청주시 서원구...", "진주시 평거로...", not "충청북도
-- 청주시..." or "경상남도 진주시...") - _ADMIN_HEAD_RE only ever matches a
-- *leading* province name, so these would stay unresolvable even with the
-- province above seeded. A city-level region also reads more usefully to a
-- dancer than its enclosing province (Cheongju/Jinju/Changwon/Pohang, not
-- Chungbuk/Gyeongnam/Gyeongnam/Gyeongbuk) - see docs/TANGO_SOURCE_DISCOVERY
-- coverage notes and the v0.82.4 investigation this migration accompanies.
-- Pohang's own Miltang item ("PosTango", source_item_id 1277/1324) is
-- included even though the engine has not yet produced a candidate for it
-- (a separate, out-of-scope extraction gap, not a region problem) - a real,
-- currently-collected source item is evidence enough per this project's own
-- "add where a real Source/Event already exists, not to round out a list"
-- rule.
--
-- Every one of these rows starts city-derivable only through an operator's
-- own venue resolution (unchanged - venue_resolution.py's own rule: nothing
-- promotes a raw string to a resolved venue automatically). Until that
-- happens, runtime/venue_resolution.guess_region_label() gives a reader a
-- read-only, non-authoritative label so the region is not blank meanwhile -
-- see runtime/events_api.py's present().

INSERT INTO regions (code, country, city, name) VALUES
    ('KR-DAEGU',      'South Korea', 'Daegu',      '대구'),
    ('KR-ULSAN',      'South Korea', 'Ulsan',      '울산'),
    ('KR-GYEONGGI',   'South Korea', 'Gyeonggi',   '경기'),
    ('KR-CHUNGBUK',   'South Korea', 'Chungbuk',   '충북'),
    ('KR-GYEONGBUK',  'South Korea', 'Gyeongbuk',  '경북'),
    ('KR-GYEONGNAM',  'South Korea', 'Gyeongnam',  '경남'),
    ('KR-JEJU',       'South Korea', 'Jeju',       '제주'),
    ('KR-CHEONGJU',   'South Korea', 'Cheongju',   '청주'),
    ('KR-JINJU',      'South Korea', 'Jinju',      '진주'),
    ('KR-CHANGWON',   'South Korea', 'Changwon',   '창원'),
    ('KR-POHANG',     'South Korea', 'Pohang',     '포항')
ON CONFLICT (code) DO NOTHING;
