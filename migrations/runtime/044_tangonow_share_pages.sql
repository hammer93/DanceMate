-- DanceMate v0.96.32 - read TangoNOW through the crawl surface it publishes.
--
-- SRC-W-002 has collected nothing since 2026-09-25. Its registered endpoint
-- is the provider's Firestore `documents.list`, which answered an
-- unauthenticated GET with complete event documents when the source was
-- registered in v0.82 and now answers HTTP 403: the public read rule was
-- withdrawn. v0.96.31 classified that correctly as ACCESS_DENIED and stopped
-- the 133 pointless retries, which is where it had to leave it.
--
-- Two weeks before the 403, on 2026-09-12, ktnow.kr's robots.txt had already
-- said what the operator wanted, and it says it in the file's own words:
--
--     # [데이터 보호 2026-09-12] 전체 이벤트 번들 JSON 은 수집 대상 아님(권고).
--     #   /events-snapshot 은 정확히 그 경로(+쿼리)만.
--     # /events-snapshot-week 는 Googlebot 홈 렌더가 쓰므로 허용 유지.
--     #   /e/ 공유 페이지도 허용.
--     Disallow: /events-bundle
--     Disallow: /events-snapshot$
--     Disallow: /events-snapshot?
--
-- So the bundle endpoint is out by instruction, not by capability. Measured
-- live on 2026-10-13 from a logged-out client with no token of any kind:
-- `/` and `/?mode=event` return the same 7.7KB JS shell holding no event
-- data; `/events-snapshot-week` and the bundle Cloud Function both answer 401
-- `appcheck_required`; Firestore answers 403. A real headless Chrome session
-- gets an App Check token, is still refused by both data endpoints, and shows
-- the site's own "이 날 일정 없어요" - and clicking the logo issues no network
-- request whatsoever, so the operator's list is simply not ours to read.
--
-- `/sitemap-events.xml` answered 200 with 58 URLs, every one upcoming, and
-- every `/e/occ_<hash>` page it lists answered 200 with a complete,
-- server-rendered schema.org `Event`: name, startDate and endDate with a KST
-- offset, location, organizer. That is a crawl surface published in order to
-- be crawled, declared in the same robots.txt, read one page per second as
-- its own Crawl-delay asks.
--
-- Nothing is created or deleted here. The source keeps its key, its genre,
-- its interval and its history; what changes is which of the provider's own
-- public surfaces it reads. Its `url` moves with the parser so the Admin's
-- source page and `_detail_url()` provenance both point at the surface that
-- is actually being read.
UPDATE sources
SET url = 'https://ktnow.kr/sitemap-events.xml',
    config = jsonb_set(
        jsonb_set(config, '{parser}', '"tangonow_share_pages"'::jsonb, true),
        '{board_urls}',
        '["https://ktnow.kr/sitemap-events.xml"]'::jsonb,
        true
    ),
    updated_at = now()
WHERE source_key = 'SRC-W-002'
  AND config->>'parser' = 'tangonow_firestore';
