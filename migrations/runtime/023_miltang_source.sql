-- DanceMate v0.83 Source Application - register Miltang (밀땅) as a
-- SECONDARY/DIRECTORY source, per docs/MILTANG_TANGODORI_SOURCE_ANALYSIS.md.
--
-- Registered DISABLED, matching 021's own policy for a source with no
-- established auto-activation history: an operator Tests it, then
-- explicitly enables it. Interval is 360 minutes - conservative, well past
-- the "최소 240분 이상" floor this task asked for, matching the interval
-- already used for the other two DIRECTORY/AGGREGATOR sources in 021.
--
-- authority_level SECONDARY, source_role DIRECTORY (the schema's closest
-- fit to "SECONDARY/DIRECTORY" - `sources_role_check` does not have a
-- lower tier than DIRECTORY/AGGREGATOR): the analysis found several
-- Miltang records whose image path is `storage/imports/ktnow_...` and
-- whose title/date/venue/source-link match SRC-W-001/002's own public
-- data exactly, so Miltang must never be treated as more authoritative
-- than the sources it may itself be republishing.
--
-- url / config.board_urls are the real collection targets (Section 6:
-- "홈페이지가 아니라 실제 collection target"), not miltang.com's own
-- homepage - `/milongas` (day-scoped, widened by config.days_ahead - see
-- runtime/collectors.py's own days_ahead gate) and `/notices` (unpaged,
-- not date-scoped).

INSERT INTO sources (
    source_key, name, platform, source_role, url, genre_id,
    authority_level, queries, config, enabled, collection_interval_minutes, notes
) VALUES
    (
        'SRC-W-005', 'Miltang', 'WEB', 'DIRECTORY',
        'https://miltang.com/milongas',
        (SELECT genre_id FROM genres WHERE code = 'TANGO'),
        'SECONDARY', '[]'::jsonb,
        jsonb_build_object(
            'parser', 'miltang_ssr',
            'board_urls', jsonb_build_array(
                'https://miltang.com/milongas',
                'https://miltang.com/notices'
            ),
            'days_ahead', 13
        ),
        FALSE, 360,
        'v0.83 Source Application. Secondary directory - KTNow(SRC-W-002) duplicate ' ||
        '가능(일부 레코드의 이미지 경로가 storage/imports/ktnow_...이고 제목/날짜/장소/' ||
        '원문 링크가 KTNow 공개 데이터와 일치하는 사례 확인됨), 자동 dedup은 신규 코드 ' ||
        '없이 기존 venue_aliases + duplicates.classify()가 처리함. 원문 LINK가 있으면 ' ||
        '항상 그쪽이 우선이며, 이 소스는 그 원문을 대체하지 않음(profile/root 링크도 ' ||
        'source_url로 승격하지 않음). /terms, /privacy 모두 404 - 별도 공개 이용약관 ' ||
        '없음(재사용 license가 아니라 기술적 공개성뿐이므로 저빈도 유지). robots.txt는 ' ||
        '/admin, /more, /requests, /nickname, /auth/만 차단하고 이 두 collection ' ||
        'target(및 week/date/region_id 파라미터)은 명시적으로 허용함.'
    )
ON CONFLICT (source_key) DO NOTHING;
