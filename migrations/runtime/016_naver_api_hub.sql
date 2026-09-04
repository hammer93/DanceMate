-- 016 naver_api_hub
--
-- NAVER_CLIENT_ID / NAVER_CLIENT_SECRET are NAVER API HUB credentials, not
-- legacy Naver Developers keys. The collector now talks to
-- naverapihub.apigw.ntruss.com with the gateway's own headers, and that
-- subscription serves one search the runtime had no platform for: webkr.
--
-- Blog and cafe already had platforms. This adds the third so a web-search
-- source can be registered if one is ever wanted. No source row is created
-- here: a platform being possible is not a reason to start collecting from it.

ALTER TABLE sources DROP CONSTRAINT IF EXISTS sources_platform_check;

ALTER TABLE sources ADD CONSTRAINT sources_platform_check CHECK (platform IN (
    'DAUM_CAFE', 'NAVER_CAFE', 'NAVER_BLOG', 'NAVER_WEB',
    'FACEBOOK', 'WEB', 'DIRECTORY'
));
