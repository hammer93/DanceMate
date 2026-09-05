# MILTANG · TANGODORI · KTNow SOURCE ANALYSIS

조사 기준 시각: **2026-09-05 KST**  
범위: 공개 접근 가능한 HTML, JavaScript bundle, route payload, robots.txt, sitemap, 약관, 브라우저 비로그인 요청. 로그인·쿠키·인증 우회, 비공개 API, 대량 pagination은 사용하지 않았다.

## 1. Executive Summary

- **Miltang은 기술적으로 수집 가능하다.** 목록과 상세가 SSR HTML이며 상세에는 Schema.org JSON-LD가 있다. 다만 일부 이미지 경로가 `storage/imports/ktnow_...`이고 KTNow와 동일한 행사·원문 링크가 확인되어 **PRIMARY가 아니라 SECONDARY/DIRECTORY**로 사용해야 한다.
- **Tangodori는 기술적으로 가장 읽기 쉽지만 자동 수집 대상으로 권장하지 않는다.** Nuxt SSR과 route별 `_payload.json`에 구조화 데이터가 있으나, 공개 약관이 scraping 및 API abuse를 금지한다. 명시적 허가 전에는 `DO_NOT_USE`가 안전하다.
- **KTNow가 세 사이트 중 가장 가치가 높다.** React/Vite SPA의 현재 공개 피드는 `eventsBundle?days=14` Cloud Function을 사용하고, 기존 `ktangoguide` Firestore의 `events`와 `milongas` collection도 비로그인 REST GET이 가능하다.
- Tangodori에서 확인한 KTNow 표기 이벤트는 client-side로 KTNow를 직접 읽는 형태가 아니다. Tangodori의 Nuxt 서버가 자체 numeric ID와 정규화된 ISO 시각을 가진 payload를 제공한다. 가장 그럴듯한 설명은 **서버 측 또는 사전 배치 import가 KTNow의 공개 structured feed를 입력으로 사용**한다는 것이다. partnership 여부는 공개 근거가 없어 `UNKNOWN`이다.

## 2. Method and Safety Boundary

확인한 공개 표면:

- Miltang: `/milongas`, `/milongas/{id}`, `/places`, `/places/{id}`, `/notices`, `/notices/{id}`, `robots.txt`, `sitemap.xml`, 공개 JS bundle
- Tangodori: home, `/milongas`, city page, `/events/{id}`, route `_payload.json`, `/about`, `/terms`, `/privacy`, `robots.txt`, `sitemap.xml`, 공개 Nuxt bundle
- KTNow: home, 공개 JS chunks, `robots.txt`, `sitemap.xml`, 브라우저가 사용하는 `eventsBundle`, Firestore REST `events?pageSize=1` 및 `milongas?pageSize=1`

요청량을 줄이기 위해 KTNow Firestore는 `pageSize=1`로 schema만 확인했다. `eventsBundle`은 현재 프런트가 요청하는 14일 범위 호출만 사용했고 전체 Firestore pagination은 수행하지 않았다.

## 3. Miltang

### Operator and launch period

- Operator: **UNKNOWN**. 공개 About/Terms/Privacy 링크와 법인·운영자 표기는 찾지 못했다.
- Domain registration: `miltang.com`은 Verisign RDAP 기준 2019-11-04 등록이다.
- Current service launch period: **2026년 6월 전후로 추정**. sitemap에서 확인한 가장 이른 현재 콘텐츠 lastmod는 2026-06-13이고, 2026-09-04까지 계속 갱신됐다. 도메인 등록일과 현재 서비스 출시일은 동일하다고 볼 수 없다.
- Evidence: `https://rdap.verisign.com/com/v1/domain/miltang.com`, `https://miltang.com/sitemap.xml`

### Tech stack and rendering

| Item | Finding |
|---|---|
| Rendering | **SSR with client enhancement**. raw HTML에 제목·날짜·시간·장소·주소·주최·원문 링크가 있다. |
| Server clues | `openresty`; `XSRF-TOKEN` cookie와 CSRF meta가 있어 Laravel 계열 서버로 추정한다. |
| Frontend clues | Vite asset, Alpine 동작, utility CSS. SPA로 볼 근거는 없다. |
| JSON | 상세 페이지에 Schema.org `Event` 또는 `Place` JSON-LD가 있다. 목록에는 JSON-LD가 없지만 실제 카드 데이터가 HTML에 있다. |
| Public API | **발견하지 못함**. 공개 bundle에서 Firebase, Supabase, GraphQL, event REST GET endpoint는 확인되지 않았다. |
| Recommended parser | 목록 SSR HTML로 ID 탐색 → 상세 JSON-LD + 보조 HTML 필드 파싱. |

주요 target:

- `https://miltang.com/milongas?week=YYYY-MM-DD&date=YYYY-MM-DD&region_id=N`
- `https://miltang.com/milongas/{id}`
- `https://miltang.com/notices`
- `https://miltang.com/notices/{id}`
- `https://miltang.com/places`
- `https://miltang.com/places/{id}`

### Observed event schema

| DanceMate-style field | Public evidence | Quality |
|---|---|---|
| `event_id` | numeric path segment, e.g. `731` | explicit |
| `title` | HTML heading + JSON-LD `name` | explicit |
| `date` | HTML `DATE` + JSON-LD `startDate` | explicit |
| `start_time`, `end_time` | HTML `TIME`, e.g. `19:00~23:00` | explicit, not present in sampled JSON-LD |
| `venue_name` | HTML `PLACE` + JSON-LD `location.name` | explicit |
| `venue_id` | event detail public markup에서 확인되지 않음 | UNKNOWN |
| `organizer` | HTML `ORG` + JSON-LD `organizer.name` when present | optional plain text |
| `region` | list filter/card and Place page | explicit at list/place level |
| `address` | detail HTML + JSON-LD PostalAddress | explicit |
| `source_url` | HTML `LINK` | optional; event post 대신 profile/root일 수 있음 |
| `recurrence` | `매주 토요일` 같은 visible label | explicit label; series ID/override model은 미노출 |
| `notice_type` | `/notices` UI에서 행사/공지 유형 표시 | route/UI level |
| `created_at`, `updated_at` | 상세에는 없음. sitemap `lastmod`는 page freshness일 뿐 record timestamp로 사용하면 안 됨 | UNKNOWN |

### Venue master

Miltang은 장소를 별도 entity로 운영한다. `/places`에서 44개 상세 링크가 확인됐고 `/places/{id}`는 `Place` JSON-LD로 name, address, telephone, image를 제공한다. Event detail도 venue name/address를 embed하지만 sampled markup에서 `/places/{id}` 관계나 `venue_id`는 노출되지 않았다.

DanceMate 매핑 적합성은 높다. 정규화 키는 `(normalized venue name, normalized road/lot address)`가 적합하며, Miltang place ID는 보조 external ID로만 보존해야 한다.

### Organizer and recurrence

- Organizer: 별도 organizer route/entity는 발견하지 못했다. event 속성의 plain text이며 JSON-LD에서는 `Organization.name`으로 포장된다.
- Recurrence: `매주 수요일`, `매주 토요일` 같은 label과 구체 event date가 함께 노출된다. series ID, exception, cancellation override 구조는 공개 markup에서 확인되지 않았다.

### Source links and samples

| Miltang event | Date / time | Venue | Original source | Platform |
|---|---|---|---|---|
| [The PISTA Milonga](https://miltang.com/milongas/731) | 2026-09-05 19:00–23:00 | PISTA, 서울 | `https://www.facebook.com/jiyu.banny`, `https://www.instagram.com/pista.tango/` | Facebook profile + Instagram profile |
| [Milonga La Vida](https://miltang.com/milongas/840) | 2026-09-05 19:30–23:30 | Amigo, 부산 | `https://cafe.daum.net/amigostudio` | Daum Cafe root |
| [Milonga ON](https://miltang.com/milongas/894) | 2026-09-05 19:00–23:00 | El Tango, 서울 | `https://cafe.daum.net/eltangocafe`, `https://www.facebook.com/eltangomilonga` | Daum Cafe + Facebook profile |
| [2026 Korea Special Tango Week](https://miltang.com/notices/8) | 2026-09-09–14, 일자별 다름 | Otra Tango Club, 서울 | `https://www.facebook.com/groups/760893148271767/posts/1446442926383449/` | Facebook post |
| [BUSAN TANGO FESTIVAL](https://miltang.com/notices/12) | 2026-10-21–29 | Detango, 부산 | `https://www.facebook.com/share/p/1ANKLmedXp/` | Facebook post |

원문 링크는 존재하지만 앞의 세 sample처럼 profile/cafe root인 경우가 있다. 따라서 provenance quality는 좋지만 항상 event-level canonical URL인 것은 아니다.

### Freshness

- 최근 7일/당일 upcoming: 2026-09-05 목록에서 서울과 부산 행사를 모두 확인했다.
- 최근 30일 upcoming: 2026-09-09–14 서울 Special Tango Week와 2026-10-21–29 부산 festival이 노출된다.
- sitemap은 570 milonga detail, 44 place detail, 16 notice detail을 열거한다. 이것은 inventory 규모이지 모두 upcoming이라는 뜻은 아니다.

### robots and terms

- robots: **PARTIAL, target allowed**. `/admin`, `/more`, `/requests`, `/nickname`, `/auth/`를 차단하고 milonga의 week/date/region parameter는 명시적으로 허용한다.
- Terms/Privacy: `/terms`와 `/privacy`는 404였다. 공개 수집·재사용 허용 문구도 찾지 못했다.
- 해석: 기술적 공개성과 robots 허용은 재사용 license가 아니다. 낮은 빈도, truthful User-Agent, 원문 provenance 보존, 운영자 문의가 안전하다.

### Role and score

Miltang은 **Secondary Evidence / Directory-Aggregator**다. sampled `Milonga ON`과 두 notice의 이미지 경로가 `storage/imports/ktnow_...`였고, BUSAN TANGO FESTIVAL의 제목·날짜·장소·Facebook source가 KTNow 공개 bundle과 일치했다.

| Metric | Score |
|---|---:|
| Public Access | 5 |
| Event Freshness | 5 |
| Structured Data | 4 |
| Date Accuracy | 5 |
| Time Accuracy | 5 |
| Venue Accuracy | 5 |
| Source Provenance | 4 |
| Parser Ease | 4 |
| Stability | 4 |
| **Total** | **41/45** |

Recommended use: **C. SSR HTML parsing + D. individual page parsing**, with JSON-LD first. `PRIMARY`가 아니라 `SECONDARY/DIRECTORY`로 저장하고 original link가 실제 post이면 canonical provenance로 승격한다.

## 4. Tangodori

### Operator and launch period

- Operator: 공개 표기는 **The Tangodori Team**. Terms는 Tangodori가 제공자라고 쓰지만 operating entity와 관할법은 아직 확정되지 않았다고 명시한다.
- Launch period: domain RDAP 등록 2026-03-09, Terms update 2026-06-27, 첫 공식 blog post 2026-07-11. 현재 서비스 출시는 **2026년 3–7월 사이로 추정**한다.
- Evidence: `https://rdap.verisign.com/com/v1/domain/tangodori.com`, `https://tangodori.com/about`, `https://tangodori.com/terms`, `https://tangodori.com/blog/welcome-to-the-tangodori-blog`

### Tech stack and public data path

| Item | Finding |
|---|---|
| Rendering | **Nuxt SSR/Hybrid**. raw HTML에 실제 event content가 있고 `X-Powered-By: Nuxt`, `__NUXT__` hydration data가 있다. |
| Edge | Cloudflare |
| Route data | `/ko/events/{numeric_id}/_payload.json?_b={build-id}` returns public JSON encoded as Nuxt/devalue payload. |
| Client stack | Nuxt/Vue. 공개 main bundle에서 Firebase, Supabase, GraphQL, KTNow client call을 찾지 못했다. |
| Public API | documented external API는 발견하지 못함. Route payload는 공개 데이터 endpoint지만 build parameter와 Nuxt encoding에 결합돼 있다. |

Event `1108` payload에서 관찰한 fields:

`kind`, `id`, `title`, `description`, `startAt`, `endAt`, `timeZone`, `utcOffsetMinutes`, `country`, `region`, `city`, `address`, `addressName`, `price`, `currency`, `flyerUrl`, `externalSource`, `externalUrl`, `tags`, `registrationMode`, `status`, `publishedAt`, `organization`, `type`, `djs`, `organizers`, `instructors`, `recurrence`.

Tangodori의 event ID는 numeric이고 KTNow Firestore document ID는 20-character string이다. Tangodori payload는 UTC offset이 포함된 ISO timestamp와 자체 region/type/organization 모델로 재구성된다. 이는 브라우저가 KTNow를 직접 표시하는 passthrough가 아니라 Tangodori 쪽 persistence 또는 server transform이 있음을 뜻한다.

### KTNow-attributed events

| Tangodori URL | Title | Date / time | Venue | Attribution field | KTNow URL |
|---|---|---|---|---|---|
| `https://tangodori.com/ko/events/1108` | PRACTILONGA | 2026-09-02 19:30–22:30 KST | Tango Brujo 주소, 서울 | `externalSource = ktnow-kr` | `https://ktnow.kr/?mode=event` |
| `https://tangodori.com/ko/events/527` | The PISTA Milonga | 2026-08-15 19:00 KST | PISTA, 서울 | visible attribution + same external URL | `https://ktnow.kr/?mode=event` |
| `https://tangodori.com/ko/events/578` | 쁘롱가 | 2026-08-19 21:15 KST | Amigo, 부산 | visible attribution + same external URL | `https://ktnow.kr/?mode=event` |

KTNow link는 document detail이나 Firebase URL이 아니라 모두 generic `/?mode=event` route였다. 따라서 Tangodori만으로 정확한 KTNow document ID를 복원할 수 없다.

### Import mechanism hypotheses

| Hypothesis | Evidence for | Evidence against | Confidence |
|---|---|---|---|
| KTNow public API/Firestore → server-side batch import | explicit `externalSource=ktnow-kr`; exact event facts; KTNow has public structured endpoints | importer code/schedule is not public; document ID is not preserved | **MEDIUM-HIGH** |
| Firebase Firestore direct in Tangodori browser | KTNow itself uses Firestore | Tangodori bundle has no Firebase; raw SSR/payload already contains copied records | **LOW** |
| HTML crawling | publicly rendered KTNow UI exists | KTNow raw HTML is an empty SPA shell; structured endpoints are much easier and more accurate | **LOW** |
| Manual import | numeric Tangodori IDs and transformed schema could be created by an admin tool | volume and systematic attribution favor automation | **LOW-MEDIUM** |
| Organizer import | Tangodori supports studio/organizer publishing | sampled records explicitly credit KTNow, not an organizer | **LOW** |
| Partnership/feed | technically possible | no public partnership statement or dedicated feed URL | **UNKNOWN / LOW** |

Final assessment: **KTNow public structured data를 입력으로 쓰는 Tangodori server-side/offline import가 가장 가능성이 높다.** Firestore REST인지 `eventsBundle`인지, 또는 별도 feed인지까지는 공개 근거로 확정할 수 없다.

### robots and terms

- robots: generic `User-agent: *`에 `Allow: /`; Content-Signal은 `search=yes, ai-train=no, use=reference`. GPTBot, ClaudeBot 등 named bot은 차단한다.
- Terms updated 2026-06-27: acceptable use에서 **“scrape or abuse the APIs”를 금지**한다.
- Decision: robots만 보면 검색/참조가 가능하지만 Terms가 automated scraping을 금지한다. operator의 서면 허가나 공식 feed 계약 없이는 DanceMate collector source로 구현하지 않는다.

Technical score: **42/45**. 점수는 데이터 품질을 뜻하며 약관상 사용 가능성을 뜻하지 않는다. Recommended use: **DO_NOT_USE for automated ingestion; manual reference or permission request only**.

## 5. KTNow

### Operator, frontend, and backend

- Operator: 공개 footer의 `created by 포올`.
- Frontend: **React/Vite SPA**. raw HTML은 약 7.5 KB shell로 event data가 없고 렌더링 후 일정이 나타난다.
- Firebase project: **`ktangoguide`**. public JS config에서 project ID, auth domain, storage bucket이 확인됐다. API key 자체는 문서에 복사하지 않는다.
- Current public feed: `https://asia-northeast3-ktangoguide.cloudfunctions.net/eventsBundle?days=14`
- Same-origin fallback in bundle: `/events-snapshot-week`
- Firestore public REST:
  - `https://firestore.googleapis.com/v1/projects/ktangoguide/databases/(default)/documents/events?pageSize=1`
  - `https://firestore.googleapis.com/v1/projects/ktangoguide/databases/(default)/documents/milongas?pageSize=1`

### Public browser/request findings

The current frontend bundle constructs `eventsBundle?days=14` and performs an unauthenticated GET. A single reproduction returned HTTP 200 with top-level fields:

`v`, `dataVersion`, `generatedAt`, `synth`, `main`, `archived`, `brands`.

At the time of inspection it contained 346 `main` records, 28 archived records, and 83 brands. The response was about 565 KB. This is a snapshot, not a stable count.

Observed live `main` fields:

`id`, `brandId`, `brandName`, `category`, `inboxPrimaryCategory`, `inboxEventSubType`, `region`, `area`, `normalizedTime`, `start_date`, `end_date`, `title`, `place`, `org`, `host`, `dj`, `level`, `orgContact`, `link`, `sourceLink`, `price`, `description`, `weeks`, `status`, `posterUrl`, `imageUrls`, `thumbnailUrl`, `scheduleId`, `source`, `isTrusted`, `createdAt`, `date`, `isLongTerm`, `badges`, `isRegularSchedule`, `time`, `day`, `updatedAt`.

The sampled BUSAN TANGO FESTIVAL record carried date range, venue, source link, poster, status, source, created/updated timestamps and category. This is richer than the public UI and is directly usable after cutoff/status filtering.

### Firestore

- Project: `ktangoguide`
- Public read: **YES at inspection time**. Unauthenticated `documents.list` with `pageSize=1` returned 200 for both `events` and `milongas`.
- Observed collections in public frontend code: `events`, `milongas`, `settings`, `proposals`. Only `events` and `milongas` list endpoints were tested.
- `events` sample fields include `title`, `date`, `time`, `place`, `price`, `region`, `regionLarge`, `regionSmall`, `org`, `host`, `dj`, `status`, `archived`, `link`, `source`, `sourceType`, `createdAt`, `updatedAt`, images and brand fields.
- `milongas` is a brand/schedule entity with `name`, `representative`, `linkItems`, `schedule`, `ownerIds`, images and timestamps.
- No write, auth-rule probing, or unauthorized collection access was attempted.

### DanceMate TangoNOW compatibility

| Comparison | Result |
|---|---|
| Host/project | Existing `runtime/tangonow_discovery.py` targets Firestore project `ktangoguide`; live frontend config is the same project. |
| Collection | Existing collector uses `events`; live public REST still exposes `events`. |
| Field names | Existing parser's confirmed names (`title`, `date`, `time`, `place`, `region*`, `org`, `dj`, `price`, `description`, `createdAt`, `updatedAt`, status flags) remain present. |
| Document shape | Direct Firestore remains typed-value `Document`. Current frontend `eventsBundle` is plain JSON with `main/archived/brands`, so a parser cannot switch endpoints without a shape change. |
| Same backend | **YES** for Firebase project and Firestore collection. **PARTIAL** only in response-shape compatibility between Firestore REST and the newer bundle. |

### robots and terms

- `https://ktnow.kr/robots.txt`: **PARTIAL**. `/admin/` blocked, other paths allowed, `Crawl-delay: 1`.
- Cloud Functions origin `robots.txt`: 404 (`NONE`).
- `/terms` and `/privacy` return the same SPA shell as home; no distinct public terms/privacy content was found in the current bundle.
- Absence of a visible restriction is not affirmative permission. Before sustained production collection, request operator confirmation and keep the public 14-day bundle cadence conservative.

Recommended use: **PRIMARY REGISTRY / COMMUNITY SOURCE**. Prefer the current public frontend feed for freshness and lower pagination cost if its stability and permission are confirmed; keep existing Firestore integration as a monitored fallback until a migration is deliberately implemented.

## 6. Cross-site relationship

```text
KTNow public registry / bundle
        │
        ├── Miltang imports or republishes some records
        │     └── Miltang keeps its own numeric route, venue directory and original LINK
        │
        └── Tangodori server-side/offline import is likely
              └── numeric Tangodori ID + normalized Nuxt event + externalSource=ktnow-kr
```

This is a provenance graph, not proof of a contractual feed. The public evidence supports data reuse and transformation but does not reveal the importer code, schedule, or legal relationship.

## 7. DanceMate answers

1. **Miltang을 Source로 써도 되는가?** 기술적으로 yes. 지속 수집 전 운영자 확인을 권장한다.
2. **Primary/Secondary?** Secondary/Directory.
3. **직접 크롤링 vs 원문 링크?** 목록/상세 JSON-LD를 저빈도로 읽어 discovery와 fallback metadata에 쓰고, event-level 원문 링크가 있으면 원문을 canonical provenance로 우선한다. profile/root 링크는 그대로 primary로 승격하지 않는다.
4. **Tangodori를 Source로 써야 하는가?** 현재는 no. Terms의 scraping 금지 때문에 자동 collector를 구현하지 않는다.
5. **Tangodori는 KTNow를 어떻게 가져오는가?** 공개 structured KTNow data를 서버 측 또는 사전 batch로 가져와 Tangodori schema로 변환하는 가설이 가장 강하다. exact endpoint와 partnership은 UNKNOWN.
6. **KTNow 자체를 직접 Source로 쓰는 것이 더 좋은가?** yes. 재게시 계층을 줄이고 event/source fields와 status를 직접 보존한다.
7. **세 사이트 중 가장 가치 있는 Source?** KTNow.
8. **법적/운영상 가장 안전한 접근?** official original link 우선, 운영자 허가 확인, truthful User-Agent, robots/crawl-delay 준수, 최소 기간 요청, 원문·집계 source를 구분한 provenance 보존.
9. **v0.82/v0.83에서 바로 구현할 Source?** v0.82의 `SRC-W-002` KTNow를 유지·모니터링하고, v0.83에서 Miltang secondary parser를 dedup/provenance rule과 함께 추가 검토한다.
10. **구현하지 말아야 할 Source?** Tangodori automated ingestion은 허가 전까지 구현하지 않는다.

## 8. Implementation priority

### PRIORITY 1

- Source: KTNow
- Why: three sites 중 가장 원천에 가깝고 current public feed가 날짜·시간·장소·원문 링크·status를 구조화해 제공한다.
- Integration type: current `SRC-W-002` 유지. 별도 작업에서 Firestore와 `eventsBundle`의 운영 비용·schema drift를 비교해 endpoint migration 여부 결정.
- Expected coverage: 전국, 향후 14일 중심 + 장기 special events.
- Risk: 공개 rule/Cloud Function 변경, Terms 부재, 565 KB snapshot, poster dependence.
- Effort: low to medium.

### PRIORITY 2

- Source: Miltang
- Why: 서울·부산 포함 전국 SSR coverage와 venue master, 원문 LINK가 있다.
- Integration type: secondary SSR/JSON-LD parser; `(date, time, venue, title)` dedup 후 KTNow match이면 별도 event를 만들지 않는다.
- Expected coverage: weekly milongas + notice/festival + venue enrichment.
- Risk: aggregator duplication, fee 누락, profile/root source links, Terms 부재.
- Effort: medium.

### PRIORITY 3

- Source: Tangodori
- Why: data quality와 multi-city coverage는 높다.
- Integration type: **do not implement without written permission**. 허가를 받으면 Nuxt SSR 또는 official API/feed를 협의한다.
- Expected coverage: 한국 주요 도시와 해외 도시.
- Risk: Terms가 scraping/API abuse를 금지, KTNow 중복, build-coupled payload.
- Effort: technically low, legal/operational blocker high.

## 9. Raw endpoints and evidence

- `https://miltang.com/robots.txt`
- `https://miltang.com/sitemap.xml`
- `https://miltang.com/milongas`
- `https://miltang.com/places`
- `https://miltang.com/notices`
- `https://tangodori.com/robots.txt`
- `https://tangodori.com/terms`
- `https://tangodori.com/privacy`
- `https://tangodori.com/about`
- `https://tangodori.com/ko/events/1108`
- `https://tangodori.com/ko/events/1108/_payload.json?_b=050c37a1-75e3-44ec-8b77-dffc73e84f11`
- `https://ktnow.kr/robots.txt`
- `https://ktnow.kr/`
- `https://asia-northeast3-ktangoguide.cloudfunctions.net/eventsBundle?days=14`
- `https://firestore.googleapis.com/v1/projects/ktangoguide/databases/(default)/documents/events?pageSize=1`
- `https://firestore.googleapis.com/v1/projects/ktangoguide/databases/(default)/documents/milongas?pageSize=1`

이번 조사(위 1-9절) 자체는 collector, DB, Source registration, scheduler, deployment, production configuration을 변경하지 않았다. 아래 10절은 그 이후 실제로 구현된 상태를 기록한다(2026-09-05, v0.83 Source Application).

## 10. Implementation Update (v0.83)

구현 세부사항은 `docs/TANGO_SOURCE_IMPLEMENTATION.md`의 "SRC-W-002 eventsBundle" 및 "SRC-W-005 — Miltang" 절을 최종 기준으로 한다. 이 절은 조사 결론이 실제로 어떻게 반영됐는지만 요약한다.

- **TangoNOW(SRC-W-002)**: 기존 Firestore 경로를 그대로 유지·안정화했다. `eventsBundle`은 실제 요청으로 재확인한 결과 요청 수/과거 데이터량 측면에서 유리하지만, 하나의 배열 안에 날짜 필드 표기가 세 가지(`date`, `start_date`/`end_date`, `startDate`/`endDate`)로 섞여 있는 등 조사 문서가 포착하지 못한 스키마 이질성이 실제로 확인됐다. `parse_bundle()`/`discover_bundle()`는 구현·테스트했지만 `collectors.py` dispatch에는 연결하지 않았다 — 이미 운영 중인 소스를 모니터링 기간 없이 바꾸지 않는다는 판단이다.
- **Miltang(신규 SRC-W-005)**: SECONDARY/DIRECTORY, 기본 비활성으로 등록(migration 023). `/milongas`(요일별, `week=`+`date=` 둘 다 필요 — `date=` 단독 요청은 현재 주로 조용히 되돌아가는 것을 실제 요청으로 확인, 그래서 매 페이지의 실제 표시 날짜를 요청한 날짜와 대조해 어긋나면 즉시 오류로 처리한다)와 `/notices`(날짜 없음)를 읽는다. 상세 페이지는 JSON-LD를 우선 사용하고 TIME/LINK/반복 라벨은 `<dl>`에서 보완한다.
- **KTNow 중복 처리**: 별도 dedup 코드를 추가하지 않고 기존 `venue_aliases` + `duplicates.classify()`를 그대로 사용한다. 다만 Miltang이 장소명을 `"PISTA 피스타"`처럼 영문+한글을 공백으로 합쳐 표기한다는 사실이 실제 dedup 테스트(수기로 만든 기대값이 아니라 진짜 `extract_venue()`를 호출하는 테스트)에서 드러나, 이 조사 문서가 예상하지 못했던 문제였다 — 마이그레이션 022가 두 표기를 항상 "따로" 등록해 두었기 때문에 합쳐진 문자열은 그대로는 해석되지 않았다. `"PISTA (피스타)"`처럼 괄호로 다시 표기해 기존 alias 테이블로 그대로 해석되도록 했다(코드/문서 근거는 위 구현 문서 참조).
- **Tangodori**: 구현하지 않음(11절 참조, 이 조사의 3/4/8절 결론 그대로 유지).
- **원문 LINK 승격 금지**: Miltang 상세의 LINK(카카오톡 오픈채팅/페이스북/인스타그램/다음카페 등)는 본문에 그대로 보존하되, `source_url`은 항상 이 소스 자체의 Miltang 상세 URL이다 — 원문이 profile/root 링크뿐인 경우에도 마찬가지다.
- **테스트**: fixture 기반 단위 테스트(`tests/test_tangonow_discovery.py`의 bundle 절, `tests/test_miltang_discovery.py`) 및 실제 PostgreSQL을 쓰는 통합 테스트(`tests/test_miltang_source_migration.py`, KTNow/Miltang dedup·기존 SRC-W-001~004 회귀 포함) 전체 통과 확인(격리된 clone에서 실행, 운영 DB에는 commit하지 않음).

### Live Acceptance (2026-09-05)

이후 별도 세션에서 실제 board staging DB에 migration 023을 적용하고, SRC-W-005만 대상으로 controlled one-shot collection을 1회 수행했다(scheduler 미활성화, enabled는 계속 FALSE). 결과 요약(전체 수치는 `docs/TANGO_SOURCE_IMPLEMENTATION.md`의 "Live Acceptance" 표 참조): 108건 발견·108건 신규, 최종 50건 리스트업, venue resolve 52%(26/50), 기존 alias 그대로 재사용(신규 venue 생성 0), KTNow(SRC-W-002)와의 자동 중복 병합 3건 + 사람 검토 대기 3건, Wrong Date/Time/Venue = 0, False VERIFIED = 0, Human review 개입 0건. 실측 결과에 따른 최종 enable 여부와 릴리스 여부는 해당 세션의 최종 보고서에 기록한다.

## 11. Tangodori — 미구현 사유 (요약)

3/4/8절의 결론을 그대로 따른다: Tangodori의 이용약관(2026-06-27 갱신)이 "scrape or abuse the APIs"를 명시적으로 금지한다. robots.txt나 `_payload.json` route의 기술적 접근성과 무관하게, 운영자의 서면 허가 또는 공식 feed 제공 전까지는 구현하지 않는다.

MILTANG TANGODORI KTNow SOURCE ANALYSIS COMPLETE

