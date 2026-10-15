-- DanceMate v0.96.34 - the room spelling of a venue this Master already holds.
--
-- v0.96.33 recovered 15 nights from 가또땅고's weekly notices and v0.96.34
-- reads each one's own place out of the post. Nine of them are written
-- `아미고 큰홀` - the big hall of a studio this Master has held since before
-- v0.82, under whichever name real usage registered it (venue 180 on this
-- project's own board, "Amigo Studio" on a database seeded only by
-- 022_tango_venue_aliases.sql). `normalize_alias()` is exact by design
-- (v0.96.32: nothing fuzzy, nothing by containment), so 아미고큰홀 matches
-- none of its spellings and nine real Busan milongas would carry a place
-- nobody could place.
--
-- This is one spelling, added to the venue already registered, on direct
-- evidence from the corpus rather than on a resemblance of names:
--
--   item 5598  "가또땅고 155th 수요쁘롱가 with DJ BEAST"
--              일시: 10월 07일 9:15-11:15pm
--              장소: 아미고 스튜디오 (부산진구 서면 황제주차장, 부산진구 부전로 34)
--
--   item 5691  "[부산_탱고동호회]가또땅고 10월 둘째주 일정"
--              [가또땅고 쁘롱가] 9:15~11:15pm (DJ 비스트, 아미고 큰홀)
--
-- Same club, same Wednesday, same hour, same DJ: one post labels the studio
-- and the other names the hall inside it. `_ROOM_ONLY_RE` already says a bare
-- 큰홀 is a room and not a venue, and the Master's unit is the venue - one
-- address, 부산진구 부전로 34 - so the hall resolves to the studio that holds
-- it. 아미고 작은홀 is deliberately left out: it appears only beside lessons,
-- no recovered programme is held there, and an alias nothing needs is an
-- assertion nothing has tested.
--
-- The target is identified the way 022 identifies its own groups - by the
-- venue that already owns a spelling of this name, never by creating a second
-- row for a place already registered. Nothing is created here and nothing is
-- overwritten: no new venue, no region change, and `ON CONFLICT DO NOTHING`
-- so a database where someone has already linked this spelling keeps their
-- decision.
INSERT INTO venue_aliases (venue_id, alias, normalized_alias)
SELECT a.venue_id, '아미고 큰홀', '아미고큰홀'
FROM venue_aliases a
WHERE a.normalized_alias = '아미고스튜디오'
LIMIT 1
ON CONFLICT (normalized_alias) DO NOTHING;
