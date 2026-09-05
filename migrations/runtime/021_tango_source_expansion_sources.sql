-- DanceMate v0.82 Tango Source Expansion - register the TOP 3 IMMEDIATE
-- sources from docs/TANGO_SOURCE_DISCOVERY.md (Section 15).
--
-- No existing migration ever seeds a real Source Master row (every source
-- registered so far, including SRC-W-001 K-TANGO, was added through the
-- admin console at runtime) - this migration exists because this release's
-- task explicitly asks for the migration/seed pattern, mirroring
-- 002_master_data.sql's own idempotent genre/region seed style
-- (`ON CONFLICT ... DO NOTHING`) rather than a one-off admin action.
--
-- Registered DISABLED: per this release's own instruction, a source with an
-- unclear auto-activation policy is registered disabled and left for an
-- operator to Test, then explicitly enable.
--
-- source_key / url are exactly the real collection targets (Section 6: "실제
-- collection target을 기록한다, homepage가 아니라"), not the marketing
-- homepage - matching how SRC-W-004 DanceInfo already points at its own
-- `/lessons` list rather than danceinfo.net's homepage.

INSERT INTO sources (
    source_key, name, platform, source_role, url, genre_id,
    authority_level, queries, config, enabled, collection_interval_minutes, notes
) VALUES
    (
        'SRC-W-002', 'TangoNOW', 'WEB', 'AGGREGATOR',
        'https://firestore.googleapis.com/v1/projects/ktangoguide/databases/(default)/documents/events?pageSize=300',
        (SELECT genre_id FROM genres WHERE code = 'TANGO'),
        'AGGREGATOR', '[]'::jsonb,
        jsonb_build_object(
            'parser', 'tangonow_firestore',
            'board_urls', jsonb_build_array(
                'https://firestore.googleapis.com/v1/projects/ktangoguide/databases/(default)/documents/events?pageSize=300'
            )
        ),
        FALSE, 360,
        'v0.82 Tango 확장. 전국 원천성이 가장 좋은 공개 Firestore 레지스트리(비로그인 GET, ' ||
        'firestore.googleapis.com robots.txt는 404). 문서 자체가 이미 완전한 구조라 별도 ' ||
        'HTML 상세 fetch가 없음(tangonow_discovery.parse_documents가 body를 직접 합성). ' ||
        'nextPageToken pagination, 빈 price, image-heavy record, 공개 rule 변경(401/403) ' ||
        '가능성을 방어함. Tangodori/Miltang과 중복 관측 위험 있음(원천 우선순위 최상위).'
    ),
    (
        'SRC-W-003', 'Tango Calendar Korea', 'WEB', 'DIRECTORY',
        'https://tangocalendar.kr/api/events',
        (SELECT genre_id FROM genres WHERE code = 'TANGO'),
        'SECONDARY', '[]'::jsonb,
        jsonb_build_object(
            'parser', 'tangocalendar_json',
            'board_urls', jsonb_build_array('https://tangocalendar.kr/api/events')
        ),
        FALSE, 360,
        'v0.82 Tango 확장. 공개 unpaged JSON 배열(robots ALLOW), 날짜/시간/장소/요금/' ||
        '생성수정시각이 모두 있는 구조화 API. 746개 base record 중 과거 비율이 매우 높아 ' ||
        '수집 단계 초기에 cutoff를 적용함(tangocalendar_discovery.parse_events). ' ||
        'occurrenceOverrides가 base event 위에 병합되며 isCancelled=true는 제외됨.'
    ),
    (
        'SRC-W-004', 'DanceInfo', 'WEB', 'DIRECTORY',
        'https://danceinfo.net/lessons?genre=all&category=all&location=all',
        (SELECT genre_id FROM genres WHERE code = 'TANGO'),
        'SECONDARY', '[]'::jsonb,
        jsonb_build_object(
            'parser', 'danceinfo_json',
            'board_urls', jsonb_build_array(
                'https://danceinfo.net/lessons?genre=all&category=all&location=all'
            )
        ),
        FALSE, 360,
        'v0.82 Tango 확장. 공개 SSR HTML만 사용(robots가 /api/를 막으므로 /lessons만 ' ||
        '호출). 혼합 장르 목록이라 discovery 단계에서 genreName==탱고만 통과시킴. ' ||
        '상세 페이지는 danceinfo.net 전용 마커(행사일~다가오는 추천, acquisition.py)로 ' ||
        '추출. board_urls는 등록 시점 기준 날짜별 페이지이므로 주기적 갱신이 필요함 - ' ||
        '정확한 폭은 실제 배포 시 board_urls 값을 참고할 것.'
    )
ON CONFLICT (source_key) DO NOTHING;
