-- v0.83.2 - Gwangju Metropolitan City, confirmed against a real, currently
-- collected Miltang item (Mi Vida tango studio, "광주 동구 중앙로 162-1
-- 5층") that was CREATE NEW'd during v0.83.1's Human Venue Review with
-- region_id left NULL because this row did not exist yet. Same rule as
-- every other region row in this project: added because a real Source/Event
-- already needs it, not to round out a list.
--
-- runtime/venue_resolution.py's _REGION_BY_ADMIN already mapped "광주" to
-- KR-GWANGJU since before this row existed (it had simply had nowhere to
-- resolve to). That mapping is leading-prefix-only ("광주" or "광주광역시"
-- at the start of an address) and is now guarded, everywhere it is used
-- (suggest()/prefill()'s region_hint, guess_region_label(),
-- terms_for_label()), against Gyeonggi-do's own, unrelated 광주시
-- (Gwangju-si): that city has no gu-level districts at all, so only an
-- explicit "광주광역시" or "광주" + one of this metro's own five gu (동구/
-- 서구/남구/북구/광산구) is trusted as real evidence of Gwangju Metro. A
-- bare "광주시 ..." or bare "광주 <dong>..." with no gu stays unresolved
-- rather than guessed either way.

INSERT INTO regions (code, country, city, name) VALUES
    ('KR-GWANGJU', 'South Korea', 'Gwangju', '광주')
ON CONFLICT (code) DO NOTHING;
