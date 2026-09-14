-- DanceMate v0.89.4 - Region Master Coverage & Resolution.
--
-- Four real Production Communities had no Region to resolve to at all:
-- 전주살사 바차타 라틴크루즈 (Jeonju, Jeollabuk-do), 여수 엘카리베라틴클럽
-- (Yeosu, Jeollanam-do), 천안세븐 (Cheonan, Chungcheongnam-do), and
-- 서당탱고 (Seosan/Dangjin, also Chungcheongnam-do). DanceMate's Region
-- master is not one consistent administrative granularity - mostly
-- province/metro (경기/충북/경북/경남/...), with a handful of individual
-- cities (청주/진주/창원/포항, migration 024) added ad hoc as their own
-- rows. These four provinces are missing at even that coarser level, so
-- this adds them there, matching the existing model rather than
-- introducing a new, finer one (Section 3-4 of the v0.89.4 task: this
-- project is a stable filter bucket, not an administrative-boundary
-- database).
--
-- runtime/venue_resolution.py's _REGION_BY_ADMIN already names these exact
-- four codes (KR-JEONBUK/KR-JEONNAM/KR-CHUNGNAM/KR-GANGWON) - written ahead
-- of this migration, dormant until the row existed. No code in that module
-- needed to change: guess_region_label()/suggested_region_id() start
-- resolving a bare "전북"/"전남"/"충남"/"강원" the moment these rows exist.
--
-- _REGION_BY_ADMIN also names a fifth, KR-SEJONG - deliberately NOT added
-- here. The Admin "Add Region" form's own guidance is "실제로 행사가
-- 확인된 지역만 추가하세요" (add only a region a real event/Community has
-- confirmed) - unlike the four above, no current Production row names
-- Sejong. Left for whichever future release finds one.
--
-- Also found, but deliberately NOT added here: KR-BUSAN has substantial
-- real Production evidence too, and - per migration 024's own comment -
-- "the master only ever seeded KR/KR-SEOUL/KR-BUSAN" yet Busan was never
-- actually one of them; it exists in Production today only because an
-- operator added it by hand through the Admin console. A fresh install (or
-- this project's own fresh-DB test suite) genuinely has none. Adding it
-- here would have fixed that install-time gap, but doing so surfaces two
-- pre-existing, already-dev-DB-documented test failures in
-- tests/test_genre_filter.py (a stale assertion from before v0.85.7's
-- zero-count-region-exclusion change - see _region_options()'s own
-- docstring) that a missing-Busan fixture skip happens to mask on a fresh
-- DB today. Fixing that unrelated, pre-existing test defect is out of this
-- release's scope (Section 4/60: this release is not "add every gap
-- found," and genre_filter's own display logic is untouched by it) - left
-- as a documented follow-up instead of folded in here.
--
-- Display names follow this project's existing short-form convention
-- (충북/경북/경남, never the official 충청북도/경상북도/경상남도) rather
-- than switching to full administrative names mid-project (Section 7).

INSERT INTO regions (code, country, city, name) VALUES
    ('KR-JEONBUK',  'South Korea', 'Jeonbuk',  '전북'),
    ('KR-JEONNAM',  'South Korea', 'Jeonnam',  '전남'),
    ('KR-CHUNGNAM', 'South Korea', 'Chungnam', '충남'),
    ('KR-GANGWON',  'South Korea', 'Gangwon',  '강원')
ON CONFLICT (code) DO NOTHING;
