# NAVER API HUB

Operational reference for how DanceMate talks to Naver. For where this fits
in the overall pipeline, see `docs/SOURCE_DATA_PIPELINE.md`. For the
migration history (why this changed), see the "NAVER API HUB authentication"
entry in `RELEASE_NOTES.md`.

## Host and endpoints

DanceMate's Naver collector (`engine/src/collectors/naver.py`) talks only to
**NAVER API HUB**, not the legacy Naver Developers Search API:

```
base:  https://naverapihub.apigw.ntruss.com
blog:      /search/v1/blog
cafe:      /search/v1/cafearticle
web:       /search/v1/webkr
```

These three endpoints answer `200` for DanceMate's credentials and back the
`NAVER_BLOG`, `NAVER_CAFE`, and `NAVER_WEB` platforms respectively (`news` and
`local` were probed live and are not offered - `news` returns 401 for these
credentials and `local`/`doc` do not exist for this subscription). The
response payload has the same shape the legacy API returned
(`lastBuildDate`/`total`/`start`/`display`/`items`), so parsing code is
unaffected by which host is used.

## Authentication - never mix schemes

API HUB and the legacy Search API use **different hosts and different
headers**, and the two must never be mixed - legacy headers authenticate
nothing against the API HUB gateway, and the gateway answers a bare `401`
without saying which half was wrong. There is no way to detect the mismatch
from the response alone; only source code review confirms it, which is why
the collector talks to exactly one host with exactly one header pair.

| | Legacy Naver Search API | NAVER API HUB (current) |
|---|---|---|
| Host | `openapi.naver.com` | `naverapihub.apigw.ntruss.com` |
| Headers | `X-Naver-Client-Id`, `X-Naver-Client-Secret` | `X-NCP-APIGW-API-KEY-ID`, `X-NCP-APIGW-API-KEY` |

## Credential environment variables

`NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` (no values here - see `.env`,
never committed). These are **API HUB** credentials despite the legacy-sounding
names: the variable names were kept unchanged on purpose so no deployed
`.env` had to move when the collector switched hosts. All three Naver
platforms (`NAVER_CAFE`, `NAVER_BLOG`, `NAVER_WEB`) share this one
subscription (`runtime/collectors.py:CREDENTIAL_ENV`).

## Safe diagnostics

To check which endpoints are currently reachable without risking a credential
leak: hit each endpoint, capture only the HTTP status code and response
shape (key names / item count), and never log the request headers or raw
body. `runtime/collector_errors.py` redacts both header schemes
(`X-Naver-Client-(Id|Secret)` and `X-NCP-APIGW-API-KEY(-ID)?`) from any error
message that reaches a log or the admin console, so a gateway error is safe
to surface verbatim - it names the error, never the key.

## Operational caveats

- A source that has been AUTH_FAILED for a while is worth re-checking after
  any credential or host change - it may simply have been talking to the
  wrong host with the wrong headers the whole time.
- `NAVER_WEB` is a registrable platform (migration 016), not itself a
  pre-populated source; a `webkr` source has to be created before it collects
  anything.
- Post dates from an aggregator with a long backlog (e.g. a blog with posts
  back to 2011) can carry no explicit year; the extractor's year-provenance
  rules (`EXPLICIT_YEAR` / `SOURCE_YEAR` / `UNKNOWN_YEAR` in
  `engine/src/extractor.py`) decide what happens next, not a fix to this
  collector.
