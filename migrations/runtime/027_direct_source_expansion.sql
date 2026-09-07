-- DanceMate v0.85.1 Direct Source Coverage Expansion.
--
-- v0.85.0 measured Direct Source Coverage (PRIMARY + PROMOTION_BOARD share
-- of upcoming Tango) at 5/147 = 3%: nearly all upcoming coverage came from
-- re-aggregating services (Miltang/TangoNOW/etc.), not from a community's,
-- organizer's, or studio's own posting. This migration registers the two
-- real candidates that survived live re-verification against
-- docs/tango_direct_source_candidates.csv's TOP list (30 candidates
-- investigated; most were REJECTed for a login-gated detail page or
-- Facebook's Terms - see that CSV for the full record). Both are registered
-- DISABLED, matching this project's standing pattern (021/023): a new
-- source is Tested by an operator, then explicitly enabled, never
-- auto-activated by a migration.
--
-- SRC-D-003 reuses the *existing* DAUM_CAFE collector (Kakao Cafe Search
-- API) unchanged - no new Python, only a new Source Master row scoped to a
-- different board (73b) on the same 'latindance' cafe SRC-D-001/002 already
-- read, via url_contains the same way those two already discriminate boards
-- within one cafe. Its own board is the Solo Tango community's own Tuesday
-- regular-meetup (화요정모) notice - a community's own posting, source_role
-- COMMUNITY, live-confirmed 2026-09-08: 20:00-23:30, Tango O Nada, DJ 유진,
-- 8,000원(22시 이후 5,000원) - full date/time/venue/fee/DJ fields, matching
-- v0.85.0's own Aggregator-only gap entry "Solo Tango 화요정모".
--
-- SRC-W-006 is a new WEB parser (tangoclass_discovery.py, this release):
-- tangoclass.co.kr's own public WordPress REST API
-- (`/wp-json/wp/v2/posts`), robots.txt ALLOW except /wp-admin/, no login,
-- full post body already in the JSON (FETCHED_FULL, no separate detail
-- fetch needed). The organizer's own instructional/practica notices,
-- source_role ORGANIZER, live-confirmed real September posts naming
-- Hongdae/Sinsa venues and fees.

INSERT INTO sources (
    source_key, name, platform, source_role, url, region_id, genre_id,
    authority_level, queries, config, enabled, collection_interval_minutes, notes
) VALUES
    (
        'SRC-D-003', 'Solo Tango 화요정모 공지', 'DAUM_CAFE', 'COMMUNITY',
        'https://m.cafe.daum.net/latindance/73b',
        (SELECT region_id FROM regions WHERE code = 'KR-SEOUL'),
        (SELECT genre_id FROM genres WHERE code = 'TANGO'),
        'PRIMARY_COMMUNITY',
        '["화요정모", "화정 공지", "솔로땅고"]'::jsonb,
        jsonb_build_object(
            'cafe_name_hint', '라틴속으로',
            'url_contains', jsonb_build_array('latindance', '73b')
        ),
        FALSE, 360,
        'v0.85.1 Direct Source Coverage Expansion. Solo Tango 커뮤니티 자체 화요정모 ' ||
        '공지 게시판(SRC-D-001/002와 같은 라틴속으로 카페의 다른 게시판, board=73b). ' ||
        '기존 DaumCafeSearchCollector를 그대로 재사용(신규 코드 없음), queries/' ||
        'url_contains만 이 게시판으로 스코프. 2026-09-08 실 라이브 검증: 20:00-23:30, ' ||
        'Tango O Nada, DJ 유진, 8,000원(22시 이후 5,000원) - v0.85.0 Aggregator-only ' ||
        'gap의 "Solo Tango 화요정모" 항목과 동일 행사.'
    ),
    (
        'SRC-W-006', 'TangoClass 공식 사이트', 'WEB', 'ORGANIZER',
        'https://tangoclass.co.kr/wp-json/wp/v2/posts?per_page=10',
        (SELECT region_id FROM regions WHERE code = 'KR-SEOUL'),
        (SELECT genre_id FROM genres WHERE code = 'TANGO'),
        'PRIMARY_ORGANIZER',
        '[]'::jsonb,
        jsonb_build_object(
            'parser', 'tangoclass_wp_json',
            'board_urls', jsonb_build_array(
                'https://tangoclass.co.kr/wp-json/wp/v2/posts?per_page=10'
            )
        ),
        FALSE, 360,
        'v0.85.1 Direct Source Coverage Expansion. 공식 WordPress REST API(robots ' ||
        'ALLOW, /wp-admin/ 제외 전부 허용), 로그인 불필요, 목록 응답 자체에 전체 ' ||
        'content.rendered가 있어 별도 상세 fetch가 필요 없음(runtime.tangoclass_' ||
        'discovery, FETCHED_FULL - Miltang과 동일 패턴). 2026-09 실 라이브 검증: ' ||
        '홍대 Aqua/Studio Ocho, 신사 Club Pang Tango 일정과 요금이 본문에 존재.'
    )
ON CONFLICT (source_key) DO NOTHING;
