# TANGO SOURCE DISCOVERY REPORT

조사 기준 시각: **2026-09-05 06:30 KST**  
범위: 대한민국의 **아르헨티나 탱고 행사/밀롱가**. Salsa와 Swing은 후보 페이지에 함께 노출되더라도 수집 대상으로 평가하지 않았다.

## 1. Executive Summary

- 검색어 변형 60개를 16개 묶음으로 실행했고, 신규 후보 41개와 기존 `SRC-W-001`을 직접 열었다. 후보의 목록/상세/API 샘플 20개를 추가로 열고 28개 도메인의 `robots.txt`를 확인했다.
- 바로 수집 가능한 독립 source family는 **TangoNOW, Tango Calendar Korea, DanceInfo, Miltang, Tangodori, KCCTF** 6개다. Tangodori의 8개 지역 URL은 한 source family로 계산했다.
- v0.82의 즉시 구현 후보는 **`SRC-W-002 = TangoNOW 공개 Firestore REST`**, **`SRC-W-003 = Tango Calendar Korea 공개 API`**, **`SRC-W-004 = DanceInfo 공개 HTML`**을 권한다.
- 가장 큰 발견은 JS 앱인 TangoNOW와 Tango Calendar Korea가 각각 로그인 없는 공개 JSON endpoint를 제공한다는 점이다. 프런트 HTML만 보고 `JS_ONLY`로 제외하면 안 된다.
- 가장 큰 중복 위험은 **TangoNOW → Tangodori 및 일부 Miltang 게시물**의 재배포다. 동일 제목·일시·장소를 발견하면 TangoNOW를 우선 원천으로 두고 secondary record는 병합해야 한다.
- 공식 venue가 직접 운영하는 공개 HTML 일정판은 찾기 어려웠다. PISTA, La Ventana, EN PAZ, Andante, O Nada, Amigo, De Tango, OCHO는 대부분 Facebook/Instagram, 공개 목록 서비스, 또는 로그인 필요한 카페를 사용한다.

### 조사량

| 항목 | 결과 |
|---|---:|
| Search query variants | 60 |
| 신규 candidate target URLs 직접 확인 | 41 |
| 기존 K-TANGO baseline 확인 | 1 |
| 추가 list/detail/API sample URLs 직접 확인 | 20 |
| `robots.txt` 확인 도메인 | 28 |
| 직접 연 content URLs 합계 | 62 |
| 최종 shortlist | 10 |
| ADD_NOW 독립 source family | 6 |

## 2. Search Method

### 검색어

아래 단어를 지역·플랫폼·연도와 교차 조합했다.

- `탱고 밀롱가`, `아르헨티나 탱고`, `밀롱가 일정`, `밀롱가 스케줄`, `탱고 행사`, `탱고 파티`, `탱고 페스티벌`, `탱고 마라톤`, `탱고 위크`, `탱고 정모`
- `서울`, `부산`, `인천`, `경기`, `성남`, `수원`, `대전`, `대구`, `광주`, `청주`, `춘천`, `제주`
- `Argentine Tango Korea`, `Milonga Seoul`, `Milonga Busan`, `Tango Seoul schedule`, `Korea tango milonga`
- `site:blog.naver.com`, `site:cafe.naver.com`, `site:cafe.daum.net`, `site:events1000.com`, `site:glartent.com`, `site:tangodori.com`, `site:miltang.com`
- `PISTA`, `La Ventana`, `라 벤따나`, `EnPaz`, `엔빠스`, `Tango Andante`, `Tango O Nada`, `아미고스튜디오`, `데땅고`, `OCHO`, `K-TANGO`

### 검증 절차

1. 검색 결과의 landing URL을 열고 실제 행사 데이터인지 확인했다.
2. 목록 URL과 상세 URL을 각각 열어 비로그인 접근, 응답 HTML/JSON, JS 의존성을 확인했다.
3. 독립 도메인은 `/robots.txt`를 직접 요청했다. 공개 target이 허용되고 일부 관리 경로만 차단되면 `PARTIAL`, target 자체가 차단되면 `BLOCKED`로 기록했다.
4. 최근 공지는 게시일 또는 source의 생성 시각이 2026-08-06 이후인 경우에만 `recent 30d`로 인정했다. 게시일이 없는 경우 `UNKNOWN`으로 남겼다.
5. 구체 날짜가 없는 “매주” 문구는 upcoming 수에 넣지 않았다. 날짜가 2026-09-05 이상이고 취소/보관 상태가 아닌 명시적 record만 셌다.
6. 같은 제목·날짜·시간·장소가 여러 source에 있으면 원천/공식 페이지를 Primary, directory·mirror·재게시를 Secondary로 분류했다.

### 점수

`Public Access`, `Recent Activity`, `Upcoming Coverage`, `Date Quality`, `Time Quality`, `Venue Quality`, `Fee Quality`, `Parser Ease`, `Stability`를 각각 0–5점으로 평가했다. 총점은 45점이다. 점수는 데이터 품질 지표이며, 구현 우선순위에는 **원천성·지역 보완 효과·중복성**을 별도로 반영했다.

## 3. Candidate Table

`SSR`은 행사 데이터가 최초 HTML에 있다는 뜻이다. `API`는 프런트와 별도로 공개 JSON이 확인됐다는 뜻이다. 모든 후보의 genre는 `TANGO`이며, 혼합 장르 source는 탱고 필터가 필요하다.

| # | Source / target | Domain · platform | Region · type | Login | Robots | Render | Recent / upcoming | Score | Decision · reason |
|---:|---|---|---|---|---|---|---|---:|---|
| 1 | [TangoNOW events API](https://firestore.googleapis.com/v1/projects/ktangoguide/databases/(default)/documents/events?pageSize=300) | `firestore.googleapis.com` · Firebase | 전국 · COMMUNITY | NO | NONE(API)/PARTIAL(app)¹ | JS shell + API | YES / 40 | 38 | **ADD_NOW** |
| 2 | [Tango Calendar Korea API](https://tangocalendar.kr/api/events) | `tangocalendar.kr` · independent | 서울 중심/일부 전국 · DIRECTORY | NO | ALLOW | JS shell + API | YES / 27 | 44 | **ADD_NOW** |
| 3 | [DanceInfo date list](https://danceinfo.net/lessons?date=2026-09-12&genre=all&category=all&location=all) | `danceinfo.net` · independent | 전국 · DIRECTORY | NO | PARTIAL | SSR | YES / 6+ verified | 42 | **ADD_NOW** |
| 4 | [Miltang milonga list](https://www.miltang.com/milongas?week=2026-08-31&date=2026-09-05) | `miltang.com` · independent | 전국 · COMMUNITY | NO | PARTIAL | SSR | YES / 11 on 09-05 | 40 | **ADD_NOW** |
| 5 | [Tangodori Seoul](https://tangodori.com/ko/seoul-milongas) | `tangodori.com` · directory | 서울 · DIRECTORY | NO | PARTIAL | SSR | YES / 20+ in 2 weeks | 40 | **ADD_NOW** · SECONDARY |
| 6 | [Tangodori Busan](https://tangodori.com/ko/busan-milongas) | same family | 부산 · DIRECTORY | NO | PARTIAL | SSR | YES / 18 | 40 | **ADD_NOW** · SECONDARY |
| 7 | [Tangodori Daejeon](https://tangodori.com/ko/daejeon-milongas) | same family | 대전 · DIRECTORY | NO | PARTIAL | SSR | YES / 11 | 39 | **ADD_NOW** · SECONDARY |
| 8 | [Tangodori Daegu](https://tangodori.com/ko/daegu-milongas) | same family | 대구 · DIRECTORY | NO | PARTIAL | SSR | YES / 6 | 38 | **ADD_NOW** · SECONDARY |
| 9 | [Tangodori Gwangju](https://tangodori.com/ko/gwangju-milongas) | same family | 광주 · DIRECTORY | NO | PARTIAL | SSR | YES / 3 | 37 | **ADD_NOW** · SECONDARY |
| 10 | [Tangodori Seongnam](https://tangodori.com/ko/seongnam-milongas) | same family | 경기 성남 · DIRECTORY | NO | PARTIAL | SSR | YES / 1 | 36 | **ADD_NOW** · SECONDARY |
| 11 | [Tangodori Cheongju](https://tangodori.com/ko/cheongju-milongas) | same family | 충북 청주 · DIRECTORY | NO | PARTIAL | SSR | YES / 1 | 36 | **ADD_NOW** · SECONDARY |
| 12 | [Tangodori Jeju](https://tangodori.com/ko/jeju-milongas) | same family | 제주 · DIRECTORY | NO | PARTIAL | SSR | NO / 0 | 30 | **MONITOR** · NO_RECENT_EVENTS |
| 13 | [2026 KCCTF](https://kcctf.org/ko) | `kcctf.org` · official | 춘천 · FESTIVAL | NO | ALLOW | SSR | YES / 6 sessions | 43 | **ADD_NOW** · PRIMARY |
| 14 | [Cafe de Tango Daum home](https://cafe.daum.net/_c21_/home?grpid=1Huyc) | `cafe.daum.net` · Daum Cafe | 부산 · OFFICIAL_VENUE | Detail YES | PARTIAL | SSR/frame | YES / 2 visible | 23 | **MONITOR** · LOGIN_REQUIRED |
| 15 | [Tango Amigo Daum home](https://cafe.daum.net/_c21_/home?grpid=1ZUn3) | `cafe.daum.net` · Daum Cafe | 부산 · OFFICIAL_VENUE | Detail YES | PARTIAL | SSR/frame | activity YES / UNKNOWN | 18 | **MONITOR** · LOGIN_REQUIRED |
| 16 | [Korea Tango Cooperative notice](https://koreatango.co.kr/) | `koreatango.co.kr` · official | 전국/서울 · ORGANIZER | NO | PARTIAL | SSR | latest 2026-06-07 / 0 | 27 | **ADD_LATER** · NO_RECENT_EVENTS |
| 17 | [TangoLife Association](https://tangolife.co.kr/) | `tangolife.co.kr` · official | 전국 · ORGANIZER | board YES | ALLOW | SSR | NO / 0 | 13 | **REJECT** · NO_EVENT_DATA, PRIVATE_COMMUNITY |
| 18 | [DCInside Argentine Tango gallery](https://gall.dcinside.com/mgallery/board/lists/?id=tangokorea) | `gall.dcinside.com` · forum | 전국 · COMMUNITY | NO | PARTIAL | SSR | board YES, event NO / 0 | 19 | **MONITOR** · NO_EVENT_DATA |
| 19 | [Nova Tango Naver Cafe](https://cafe.naver.com/novatango) | `cafe.naver.com` · Naver Cafe | 서울/EN PAZ · CAFE | UNKNOWN | BLOCKED | SSR shell | UNKNOWN / UNKNOWN | 6 | **REJECT** · ROBOTS_BLOCKED |
| 20 | [Social Dance Live Busan/Tango query](https://www.socialdancelive.com/?genre=tango&location=Busan&sort=latest) | `socialdancelive.com` · directory | 부산 · DIRECTORY | NO | PARTIAL | SSR | 2026-08-23 / 0 | 33 | **ADD_LATER** · mixed genre, no upcoming |
| 21 | [Milonga Sueño Dulce mirror](https://www.events1000.com/KR/Seoul/1084207278362147/Milonga-Sue%C3%B1o-Dulce) | `events1000.com` · public mirror | 서울/La Ventana · ORGANIZER | NO | PARTIAL | SSR | 2026-08-08 / 0 | 34 | **MONITOR** · DUPLICATE_ONLY risk |
| 22 | [Cafe de Tango mirror](https://www.glartent.com/KR/Busan/252403654865773/Cafe-de-Tango) | `glartent.com` · public mirror | 부산 · OFFICIAL_VENUE | NO | PARTIAL | SSR | NO / 0 | 20 | **REJECT** · NO_RECENT_EVENTS |
| 23 | [Korea Milonga Google Site — Busan Sunday](https://sites.google.com/view/tangomilongaincorea/where-are-you-now/busan/sunday) | `sites.google.com` · Google Sites | 부산 · DIRECTORY | NO | PARTIAL | SSR | UNKNOWN / 0 dated | 31 | **MONITOR** · stale recurring data |
| 24 | [EnjoyTango Milonga Orange](https://www.enjoytango.com/en/app/show.php?aid=1021) | `enjoytango.com` · directory | 서울/Andante · DIRECTORY | NO | NONE² | SSR | UNKNOWN / 0 dated | 31 | **MONITOR** · NO_RECENT_EVENTS |
| 25 | [Milongas-in Korea/Seoul](https://milongas-in.com/milongas-in-asia.php?c=Korea&city=seoul) | `milongas-in.com` · directory | 서울 · DIRECTORY | NO | PARTIAL | SSR | NO / 0 | 26 | **REJECT** · PAST_ONLY |
| 26 | [Milonga del Ayer](https://itseemstobe.tistory.com/) | `tistory.com` · blog | 서울 · BLOG | NO | PARTIAL | SSR | latest blog 2026-07-08 / 0 | 29 | **ADD_LATER** · venue enrichment only |
| 27 | [PISTA venue article](https://itseemstobe.tistory.com/entry/%ED%83%B1%EA%B3%A0-%ED%94%BC%EC%8A%A4%ED%83%80-%EB%B0%80%EB%A1%B1%EA%B0%80-%EC%95%88%EB%82%B4) | same blog | 서울/PISTA · BLOG | NO | PARTIAL | SSR | 2025-05-06 / 0 | 27 | **ADD_LATER** · static venue seed |
| 28 | [EN PAZ venue article](https://itseemstobe.tistory.com/entry/%EA%B0%95%EB%82%A8-%EB%B0%80%EB%A1%B1%EA%B0%80-%EC%97%94%EB%B9%A0%EC%8A%A4) | same blog | 서울/EN PAZ · BLOG | NO | PARTIAL | SSR | 2024-12-19 / 0 | 27 | **REJECT** · PAST_ONLY |
| 29 | [La Ventana venue article](https://itseemstobe.tistory.com/entry/%ED%99%8D%EB%8C%80-%EB%9D%BC%EB%B2%A4%EB%94%B0%EB%82%98-%EB%B0%80%EB%A1%B1%EA%B0%80) | same blog | 서울/La Ventana · BLOG | NO | PARTIAL | SSR | 2025-03-30 / 0 | 27 | **ADD_LATER** · static venue seed |
| 30 | [OCHO/홍대 schedule article](https://itseemstobe.tistory.com/entry/%ED%99%8D%EB%8C%80-%EB%B0%80%EB%A1%B1%EA%B0%80-%EC%A0%95%EB%B3%B4) | same blog | 서울/OCHO · BLOG | NO | PARTIAL | SSR | 2024-12-13 / 0 | 27 | **REJECT** · PAST_ONLY |
| 31 | [Tango Andante article](https://itseemstobe.tistory.com/entry/%ED%83%B1%EA%B3%A0-%EC%95%88%EB%8B%A8%ED%85%8C-Tango-Andante) | same blog | 서울/Andante · BLOG | NO | PARTIAL | SSR | 2025-03-17 / 0 | 27 | **ADD_LATER** · static venue seed |
| 32 | [GetBailar Tango O Nada](https://getbailar.com/venues/tango-o-nada-i-seoul) | `getbailar.com` · directory | 서울/O Nada · DIRECTORY | NO | PARTIAL | SSR | UNKNOWN / 0 dated | 29 | **ADD_LATER** · venue enrichment only |
| 33 | [Tango O Nada legacy site](http://milonga.kr/) | `milonga.kr` · official | 서울 · OFFICIAL_VENUE | NO | NONE | 298-byte blank HTML | NO / 0 | 7 | **REJECT** · NO_EVENT_DATA |
| 34 | [Seoul Argentine Tango Academy](https://seoultango.com/) | `seoultango.com` · official | 서울 · OFFICIAL_VENUE | NO | NONE | SSR | 2023-11 / 0 | 17 | **REJECT** · PAST_ONLY |
| 35 | [El Bulin](https://elbulintango.blogspot.com/) | `blogspot.com` · blog | 서울 · OFFICIAL_VENUE | NO | PARTIAL | SSR | 2016 / 0 | 26 | **REJECT** · PAST_ONLY |
| 36 | [2017 Seoul Tango Festival](https://leoyflortango.blogspot.com/) | `blogspot.com` · blog | 서울 · FESTIVAL | NO | PARTIAL | SSR | 2017 / 0 | 25 | **REJECT** · PAST_ONLY |
| 37 | [Dulce y Leo practica redirect](https://www.dulcenaleo.com/prac/) | `dulcenaleo.com` · official | 서울 · ORGANIZER | form optional | ALLOW | SSR redirect | source metadata NO / UNKNOWN | 13 | **MONITOR** · NO_EVENT_DATA |
| 38 | [ModooTango article](https://blog.modootango.com/251) | `modootango.com` · blog | 서울 · BLOG | NO | PARTIAL | SSR | NO / 0 | 20 | **REJECT** · NO_RECENT_EVENTS |
| 39 | [Tango Cafe Kakao Channel](https://pf.kakao.com/_AJwGxd/6214518) | `pf.kakao.com` · Kakao | 서울 · COMMUNITY | NO to land | ALLOW | JS-heavy | 2018 / 0 | 13 | **REJECT** · PAST_ONLY |
| 40 | [Tango Map](https://tango.bien.ltd/) | `tango.bien.ltd` · independent | 전국 주장 · DIRECTORY | NO | NONE | SSR | demo placeholders / 0 | 7 | **REJECT** · NO_EVENT_DATA |
| 41 | [Maily tango directory article](https://maily.so/allculture/posts/wdr9l431rlx) | `maily.so` · newsletter | 서울 · BLOG | modal login, article public | PARTIAL | SSR | old article / 0 | 17 | **REJECT** · PAST_ONLY |

¹ TangoNOW의 앱 domain `ktnow.kr`은 `/admin/`만 차단한다. 권장 수집 endpoint인 `firestore.googleapis.com`은 `robots.txt`가 404(`NONE`)였고 공개 GET을 직접 확인했다.  
² EnjoyTango의 robots 파일은 `User-agent: * 1`뿐이라 유효한 Allow/Disallow 지시가 없었다. 이 보고서에서는 `NONE`으로 취급한다.

## 4. Extraction Diagnostics

| Candidate family | List / detail pattern | Pagination | Latest verified | Image heavy | HTML/body extraction | Duplicate ratio | Past ratio | Access stability | Difficulty |
|---|---|---|---|---|---|---|---|---|---|
| TangoNOW | collection `.../documents/events`; detail `.../events/{20-char-id}` | `nextPageToken`; 77 variable batches for 3,639 docs | `createdAt` 2026-08-30 sample | YES | JSON fields extractable; frontend HTML has no event data | HIGH vs Tangodori/Miltang | 3,599/3,639 date-before-cutoff (98.9%) | MEDIUM; public Firebase rules may change | MEDIUM |
| Tango Calendar Korea | `/api/events`; `/api/events/{uuid}`; UI `/?eventId={uuid}` | unpaged array (746 base records) | 2026-09-02 sample create/update | NO | JSON fully extractable | MEDIUM; overlapping public schedules | 719/746 base dates before cutoff (96.4%) | HIGH-MEDIUM | EASY |
| DanceInfo | `/lessons?date=YYYY-MM-DD...`; `/lessons/{numeric-id}` | date navigation and page control | current 2026-09-05/12/17/10-11 pages | YES | date/time/venue/fee in SSR HTML | LOW-MEDIUM | LOW when date-targeted | HIGH | EASY-MEDIUM; genre filter in parser |
| Miltang | `/milongas?week=...&date=...&region_id=...`; `/milongas/{id}` | week/date/region filters, no numeric page observed | 2026-09-05 | YES | core fields SSR; fee often absent | MEDIUM-HIGH | LOW when date-targeted | HIGH | EASY-MEDIUM |
| Tangodori | `/ko/{city}-milongas`; `/ko/events/{id}` | fixed upcoming view; no pagination shown | 2026-09-05 list | NO | core fields SSR | HIGH; checked details identify `ktnow.kr` source | LOW | HIGH, but named AI bots blocked | EASY |
| KCCTF | `/ko`; program tabs embedded in page data | none | upcoming 2026-10-03–05 | NO | all sessions, venue, ticket prices extractable | LOW; official primary | LOW | HIGH | EASY |
| Daum Cafe de Tango / Amigo | `/_c21_/home?grpid=...`; `/_c21_/bbs_list`; `/_c21_/bbs_read?...&datanum=N` | board paging exists | Cafe de Tango 2026-09-03/09-01; Amigo activity 2026-09-03 | YES | home snippets only; detail demands login | LOW at official origin | MEDIUM | MEDIUM | HARD / not eligible now |
| Korea Tango Cooperative | home notice table; individual Imweb posts | board pages | 2026-06-07 | mixed | notice list SSR | LOW; official | HIGH at cutoff | HIGH | EASY |
| Social Dance Live | query string list; individual event cards | sort/filter | 2026-08-23 Tango item | YES | SSR but mixed genre | MEDIUM | HIGH at cutoff | MEDIUM-HIGH | MEDIUM |
| Events1000 / Glartent | venue mirror path; dated posts in one page | long feed; no stable page cursor observed | Sueño Dulce post 2026-08-08 | YES | post text SSR | 100% mirror by design | HIGH at cutoff | LOW-MEDIUM | MEDIUM-HARD |
| Google Sites Korea Milonga | city/day hierarchy | none | UNKNOWN | NO | recurring text SSR | HIGH as directory | UNKNOWN | HIGH | EASY but stale-risk |
| EnjoyTango / Milongas-in / GetBailar | directory venue records | site-specific browse/search | 2026-01-03 edit at Milongas-in; others UNKNOWN | NO | SSR | HIGH | HIGH/UNKNOWN | MEDIUM | EASY |
| Milonga del Ayer and venue articles | blog home/category; `/entry/{slug}` | Tistory pages | blog 2026-07-08; venue articles 2024–25 | YES | SSR article body | MEDIUM | HIGH | HIGH | EASY; enrichment only |
| DCInside | `.../lists/?id=tangokorea`; `.../view/?id=tangokorea&no=N` | `page=N` | board posts 2026-09-05 | mixed | SSR but unstructured discussion | UNKNOWN | UNKNOWN | MEDIUM | HARD; low signal |
| Naver Cafe | cafe shell/board | platform controlled | UNKNOWN | YES | target blocked by robots | UNKNOWN | UNKNOWN | LOW for collector | NOT ELIGIBLE |
| Remaining rejected sites | home/article only | none or blog paging | 2016–2023, UNKNOWN, or demo | mixed | HTML exists but no current event record | UNKNOWN | HIGH | LOW-MEDIUM | NOT USEFUL |

## 5. Verified Event Samples

`Published At`은 source가 제공한 생성/게시 시각이다. 없는 값은 추정하지 않고 `UNKNOWN`으로 남겼다. API의 UTC 시각은 `Z`, 행사 시간은 KST로 표기했다.

### TangoNOW — TOP 3 verification

List: [Firestore events collection](https://firestore.googleapis.com/v1/projects/ktangoguide/databases/(default)/documents/events?pageSize=300)  
Detail pattern: `.../documents/events/{id}`  
Login: NO · robots: `ktnow.kr` PARTIAL (`/admin/` only) · frontend: JS-only · public API: YES

| Title | Published At | Event Date | Time | Venue | Fee | Original URL |
|---|---|---|---|---|---|---|
| 밀빠쏘 | 2026-08-26T23:51:03Z | 2026-09-06 | 14:00–18:00 KST | PISTA | UNKNOWN | [Firestore document](https://firestore.googleapis.com/v1/projects/ktangoguide/databases/(default)/documents/events/l4HSkRtgLLJv2ndOa3Wq) |
| Nuevo Milonga | 2026-08-30T19:46:07Z | 2026-09-06 | 18:00–22:00 KST | EN PAZ | UNKNOWN | [Firestore document](https://firestore.googleapis.com/v1/projects/ktangoguide/databases/(default)/documents/events/M9zLS6EXkDQzJ2vEg8IU) |
| Puerto Tango | 2026-08-25T00:59:42Z | 2026-09-06 | 18:00–22:00 KST | 이데알 탱고 까페, 부산 | UNKNOWN | [Firestore document](https://firestore.googleapis.com/v1/projects/ktangoguide/databases/(default)/documents/events/klTsP5uX5YzvziR4afEF) |

### Tango Calendar Korea — TOP 3 verification

List: [public `/api/events`](https://tangocalendar.kr/api/events)  
Detail: [public `/api/events/{uuid}`](https://tangocalendar.kr/api/events/3aa58986-65da-41c4-8693-895b005d1f1c)  
Login: NO · robots: ALLOW · frontend: JS-only · public API: YES

| Title | Published At | Event Date | Time | Venue | Fee | Original URL |
|---|---|---|---|---|---|---|
| Alonga | 2026-09-02T06:06:40Z | 2026-09-06 | 14:00–18:00 KST | 탱고 안단테 | 13,000원 | [API detail](https://tangocalendar.kr/api/events/3aa58986-65da-41c4-8693-895b005d1f1c) |
| 누베르 | 2026-08-29T09:27:43Z | 2026-09-06 | 18:00–22:00 KST | 탱고 엔빠스 스튜디오 | 13,000원 | [API detail](https://tangocalendar.kr/api/events/2c88fdb1-ef6d-43df-9825-74490b75796d) |
| La Melodia | 2026-08-17T00:27:32Z | 2026-09-06 | 19:00–23:00 KST | 탱고 안단테 | 13,000원 | [API detail](https://tangocalendar.kr/api/events/ef3a7f4f-4dbf-4fd1-8fc1-33a07c8bf26c) |

### DanceInfo — TOP 3 verification

List: [2026-09-12 date page](https://danceinfo.net/lessons?date=2026-09-12&genre=all&category=all&location=all)  
Detail pattern: `/lessons/{numeric-id}`  
Login: NO · robots: PARTIAL; `/lessons` allowed, `/api/` blocked · render: SSR

| Title | Published At | Event Date | Time | Venue | Fee | Original URL |
|---|---|---|---|---|---|---|
| 러블리밀롱가 7주년 파티 | UNKNOWN | 2026-09-12 | 17:30–21:30 | 분당 실루엣, 정자동 23-1 지파크프라자 5층 | 예매 15,000원 / 현매 20,000원 | [detail](https://danceinfo.net/lessons/2401) |
| 분당 러블리 낮밀 | UNKNOWN | 2026-09-17 | 14:00–17:00 | 분당 실루엣 | 13,000원 | [detail](https://danceinfo.net/lessons/2760) |
| 탱고심바 꼬라손밀 | UNKNOWN | 2026-10-11 | 13:00–17:00 | 탱고 오나다 | 7,000/10,000/13,000원, 현매 15,000원 | [detail](https://danceinfo.net/lessons/3863) |

### Miltang

List: [2026-09-05](https://www.miltang.com/milongas?week=2026-08-31&date=2026-09-05) · Detail: `/milongas/{id}` · Login: NO · robots: PARTIAL · SSR: YES

| Title | Published At | Event Date | Time | Venue | Fee | Original URL |
|---|---|---|---|---|---|---|
| The PISTA Milonga | UNKNOWN | 2026-09-05 | 19:00–23:00 | PISTA, 서울 월드컵북로6길 49 B1 | UNKNOWN | [detail](https://www.miltang.com/milongas/731) |
| 토나다 | UNKNOWN | 2026-09-05 | 21:00–03:00 | O Nada, 서울 마포구 동교동 200-29 B1 | UNKNOWN | [detail](https://www.miltang.com/milongas/785) |
| Milonga La Vida | UNKNOWN | 2026-09-05 | 19:30–23:30 | Amigo, 부산 부산진구 부전로34 황제주차빌딩 2층 | UNKNOWN | [detail](https://www.miltang.com/milongas/840) |

### Tangodori

List: [Seoul](https://tangodori.com/ko/seoul-milongas) / [Busan](https://tangodori.com/ko/busan-milongas) · Detail: `/ko/events/{id}` · Login: NO · robots: PARTIAL · SSR: YES

| Title | Published At | Event Date | Time | Venue | Fee | Original URL |
|---|---|---|---|---|---|---|
| Alonga | UNKNOWN | 2026-09-06 | 14:00–18:00 | Tango Andante, 서울 양화로12길 24 선진빌딩 B1 | UNKNOWN | [detail](https://tangodori.com/ko/events/1158) |
| 밀빠쏘 | UNKNOWN | 2026-09-06 | 14:00–18:00 | PISTA, 서울 월드컵북로6길 49 B1 | UNKNOWN | [detail](https://tangodori.com/ko/events/1157) |

두 상세 페이지가 source를 `ktnow.kr`로 표시하므로 Tangodori는 이 표본에서는 Secondary다.

### 2026 KCCTF

Official page: [KCCTF Korean program](https://kcctf.org/ko) · Login: NO · robots: ALLOW · SSR: YES

| Title | Published At | Event Date | Time | Venue | Fee | Original URL |
|---|---|---|---|---|---|---|
| M1 환영 밀롱가 | UNKNOWN | 2026-10-03 | 15:00–20:00 | 춘천 봄내체육관 | 풀패스 240,000원; 1일권 120,000원 | [official](https://kcctf.org/ko) |
| M2 첫째 밤 밀롱가 | UNKNOWN | 2026-10-03 | 21:00–04:00 | 춘천 봄내체육관 | 풀패스 240,000원; 1일권 120,000원 | [official](https://kcctf.org/ko) |
| M3 일요 오후 밀롱가 | UNKNOWN | 2026-10-04 | 14:00–19:00 | 춘천 봄내체육관 | 풀패스 240,000원; 1일권 120,000원 | [official](https://kcctf.org/ko) |

### Cafe de Tango Daum — access failure sample

Home snippets show `[부산 / 일요일] Bu3Mil / 09월 06일` published 2026-09-01 and a `09월 04일 Viernes Milonga` post. The [board list](https://cafe.daum.net/_c21_/bbs_list?grpid=1Huyc&fldid=6KLn) and [Bu3Mil detail](https://cafe.daum.net/_c21_/bbs_read?grpid=1Huyc&fldid=6KLn&datanum=4861) were opened without a session; the detail returned a login/grade notice. Time, fee and body are therefore `UNKNOWN`. This source must not be bypassed.

### Milonga Sueño Dulce public mirror

| Title | Published At | Event Date | Time | Venue | Fee | Original URL |
|---|---|---|---|---|---|---|
| 일둘쎄 | 2026-08-08 | 2026-08-09 | 19:00–23:00 | La Ventana, 서교동 372-2 2F | 13,000원 | [mirror](https://www.events1000.com/KR/Seoul/1084207278362147/Milonga-Sue%C3%B1o-Dulce) |
| 일둘쎄 | 2026-08-01 | 2026-08-02 | 19:00–23:00 | La Ventana | 13,000원 | [mirror](https://www.events1000.com/KR/Seoul/1084207278362147/Milonga-Sue%C3%B1o-Dulce) |
| 일둘쎄 | 2026-07-24 | 2026-07-26 | 19:00–23:00 | La Ventana | 13,000원 | [mirror](https://www.events1000.com/KR/Seoul/1084207278362147/Milonga-Sue%C3%B1o-Dulce) |

최근 30일 안의 게시물이지만 기준 시각 이후의 구체 날짜가 없고 Facebook mirror이므로 `MONITOR`다.

## 6. ADD_NOW Shortlist

### 1. Tango Calendar Korea — 44/45

Score: `PA5 RA5 UC5 D5 T5 V5 F5 PE5 S4`  
746개 base record를 한 번에 주는 공개 API와 UUID detail API가 모두 200으로 응답한다. 현재 명시적 future base event 27개, 최근 표본에는 생성/수정 시각과 13,000원 요금까지 있었다.

### 2. KCCTF — 43/45

Score: `PA5 RA5 UC4 D5 T5 V5 F5 PE4 S5`  
2026-10-03~05의 공식 페스티벌 페이지로, 프로그램·시간·장소·티켓 가격이 한 페이지에서 추출된다. 원천성은 가장 높지만 연 1회성이라 전국 상시 수집 source를 대체하지는 않는다.

### 3. DanceInfo — 42/45

Score: `PA5 RA5 UC4 D5 T5 V5 F5 PE4 S4`  
날짜 목록과 numeric detail 모두 SSR이며 분당, 대전, 순천, 서울의 명시적 upcoming 탱고 공지를 확인했다. 혼합 장르라 detail의 genre가 정확히 `탱고`인지 필터링해야 하고 robots가 `/api/`를 막으므로 HTML만 사용해야 한다.

### 4. Miltang — 40/45

Score: `PA5 RA5 UC5 D5 T5 V5 F2 PE4 S4`  
날짜·주·지역 목록과 안정적인 상세 URL이 있으며 기준일에 11개 밀롱가가 노출됐다. 요금 누락이 많고 TangoNOW에서 가져온 포스터/일정이 섞여 있어 primary source로 과대평가하면 안 된다.

### 5. Tangodori — 40/45

Score: `PA5 RA5 UC5 D5 T5 V5 F1 PE5 S4`  
서울 20+, 부산 18, 대전 11, 대구 6, 광주 3, 성남 1, 청주 1개의 향후 2주 일정을 SSR HTML로 제공한다. 지역 커버리지는 훌륭하지만 확인한 상세 2건이 `ktnow.kr`를 source로 표시해 secondary fallback으로 배치해야 한다.

### 6. TangoNOW — 38/45

Score: `PA5 RA5 UC5 D5 T5 V4 F2 PE4 S3`  
전국 scene의 원천에 가장 가까운 공개 registry다. Firestore REST에서 3,639개 문서, 기준일 이후 40개 record, 최근 30일 생성/수정 122개를 확인했다. 77회의 가변 pagination과 빈 요금 필드, 공개 rule 변경 가능성이 단점이다.

## 7. ADD_LATER

- **Korea Tango Cooperative (27/45):** 공식 대회/주최자 게시판이고 SSR·robots 상태가 좋다. 최신 글이 2026-06-07 대회 결과이며 현재 upcoming이 없어 대회 시즌에 다시 점검한다.
- **Social Dance Live (33/45):** 2026-08-23 부산 Cafe de Tango의 `Milonga R&D`를 날짜·시간·장소로 노출했다. 현재 future Tango가 없고 장르 query에도 비탱고 결과가 많이 섞인다.
- **Milonga del Ayer + PISTA/La Ventana/Andante articles (27–29/45):** 주소와 정기 운영 패턴을 venue 정규화 seed로 쓰기 좋다. 최근 개별 행사 feed가 아니므로 event collector가 아니라 enrichment backlog로 둔다.
- **GetBailar Tango O Nada (29/45):** venue/address/regular schedule 보조 정보로만 사용한다. 구체 upcoming 및 게시 시각이 없다.

## 8. MONITOR

- **Cafe de Tango / Tango Amigo Daum Cafe:** 부산 공식 운영 주체의 최신 제목은 공개 home에 보이지만 상세는 로그인과 등급을 요구한다. 공개 범위 확대 여부만 감시하며 쿠키/세션 우회는 금지한다.
- **Milonga Sueño Dulce Events1000:** 최근까지 풍부한 날짜·시간·장소·요금이 보였으나 Facebook 공개 mirror이고 기준일 이후 날짜가 없다. mirror URL/갱신이 깨질 가능성이 높다.
- **Google Sites Korea Milonga:** 부산 Sunday 페이지의 `Puerto Tango 19:00–23:00, 10,000원`은 현재 TangoNOW의 2026-09-06 `18:00–22:00`과 충돌한다. 정적 정기표이므로 최신성 확인 없이 수집하면 안 된다.
- **EnjoyTango Milonga Orange:** Andante의 반복 시간·주소·요금을 제공하지만 게시/수정 시각과 명시 날짜가 없다.
- **DCInside gallery:** 2026-09-05까지 활동은 있으나 공지보다 대화·후기가 많고 날짜/장소/요금 필드가 없다.
- **Tangodori Jeju:** 기술적으로 수집 가능하나 향후 2주 결과가 0이다.
- **Dulce y Leo:** 공개 페이지가 신청 Google Form으로 이동할 뿐, source HTML에 event metadata가 없다.

## 9. REJECT

| Source | Reason |
|---|---|
| Nova Tango Naver Cafe | `ROBOTS_BLOCKED`; `cafe.naver.com`의 generic `User-agent: *`가 `/` 전체 차단 |
| TangoLife member board | `PRIVATE_COMMUNITY`, `NO_EVENT_DATA` |
| Cafe de Tango Glartent mirror | `NO_RECENT_EVENTS`, mirror instability |
| Milongas-in Korea/Seoul | `PAST_ONLY`; 다수 record가 2012–2023, 최근 edit도 구체 future event 아님 |
| EN PAZ/OCHO static Tistory pages | `PAST_ONLY`; 2024 schedule |
| `milonga.kr` | `NO_EVENT_DATA`; 200이나 298-byte blank document |
| Seoul Argentine Tango Academy | `PAST_ONLY`; 2023-11 schedule |
| El Bulin | `PAST_ONLY`; 2016 |
| 2017 Seoul Tango Festival | `PAST_ONLY` |
| ModooTango article | `NO_RECENT_EVENTS`, `NO_EVENT_DATA` |
| Tango Cafe Kakao channel | `PAST_ONLY`; 확인 가능한 내용 2018 |
| Tango Map | `NO_EVENT_DATA`; `Google Maps API 연동 예정`과 가상 주소가 있는 demo/placeholder |
| Maily tango article | `PAST_ONLY`; recurring source가 아닌 단일 기사 |

## 10. Source Duplication and Primary/Secondary Rules

| Event/source chain | Primary | Secondary | Rule |
|---|---|---|---|
| TangoNOW event → Tangodori | TangoNOW Firestore document | Tangodori detail | Tangodori가 `ktnow.kr`를 source로 명시하면 TangoNOW canonical key 사용 |
| TangoNOW event → Miltang import | TangoNOW when matching title/date/time/venue and import asset | Miltang | Miltang native-only fields만 보강; 별도 event 생성 금지 |
| Official organizer → directory | official page when publicly collectable | Tango Calendar/DanceInfo/Miltang | official URL을 canonical `source_url`로 보존 |
| Cafe de Tango Daum → public directories | Daum Cafe is conceptual primary but detail inaccessible | TangoNOW/Tangodori/Miltang | 로그인 source를 자동 수집하지 말고 public record를 수집하되 provenance 표시 |
| Facebook → Events1000/Glartent | Facebook organizer post | mirror | mirror는 `secondary_mirror=true`; primary처럼 평가하지 않음 |
| KCCTF → reposts | KCCTF official | all reposts | official program wins on date/time/fee conflict |
| Static venue directory → current calendar | current dated calendar | Tistory/Google Sites/GetBailar | static data는 venue alias/address enrichment에만 사용 |

권장 dedup key는 정규화한 `(event_date, start_time, venue_alias, normalized_title)`이고, source precedence는 `OFFICIAL_VENUE/FESTIVAL > ORGANIZER > primary registry > community directory > mirror/static directory`다.

## 11. TOP 10

### 1. Tango Calendar Korea

- Region: 서울 중심, 일부 전국
- URL/Target: [site](https://tangocalendar.kr/) · [list API](https://tangocalendar.kr/api/events) · detail `/api/events/{uuid}`
- Type: DIRECTORY · Recent Event: YES · Upcoming: 27 · Score: **44/45** · Decision: **ADD_NOW**
- Reason: 공개 JSON의 날짜·시간·장소·요금·생성/수정 시각 품질이 가장 높다. 대량 과거 record는 event date 필터로 제거한다.

### 2. KCCTF

- Region: 춘천/강원
- URL/Target: [2026 official program](https://kcctf.org/ko)
- Type: FESTIVAL · Recent Event: YES · Upcoming: 6 sessions · Score: **43/45** · Decision: **ADD_NOW**
- Reason: 공식 원천이며 2026-10-03~05 프로그램, venue, 가격이 모두 공개다. 연속 feed가 아닌 계절 source라는 점만 별도 처리한다.

### 3. DanceInfo

- Region: 전국
- URL/Target: [date list](https://danceinfo.net/lessons?date=2026-09-12&genre=all&category=all&location=all) · detail `/lessons/{id}`
- Type: DIRECTORY · Recent Event: YES · Upcoming: 6+ checked · Score: **42/45** · Decision: **ADD_NOW**
- Reason: 분당·대전·순천·서울의 행사 상세가 SSR이며 fee까지 양호하다. 혼합 장르 필터와 `/api/` robots 차단을 지켜야 한다.

### 4. Miltang

- Region: 전국
- URL/Target: [milonga list](https://www.miltang.com/milongas?week=2026-08-31&date=2026-09-05) · detail `/milongas/{id}`
- Type: COMMUNITY · Recent Event: YES · Upcoming: 11 on 09-05 · Score: **40/45** · Decision: **ADD_NOW**
- Reason: 날짜/지역 탐색과 상세 URL이 안정적이다. fee 보완과 TangoNOW 중복 제거가 필수다.

### 5. Tangodori

- Region: 서울, 부산, 대전, 대구, 광주, 성남, 청주, 제주
- URL/Target: [Seoul](https://tangodori.com/ko/seoul-milongas) · `/ko/{city}-milongas` · `/ko/events/{id}`
- Type: DIRECTORY · Recent Event: YES · Upcoming: 60+ across checked non-empty city pages · Score: **40/45** · Decision: **ADD_NOW**
- Reason: 가장 편한 SSR 지역 calendar다. 다만 TangoNOW 재배포 비율이 높아 별도 독립 source가 아닌 secondary/fallback으로 사용한다.

### 6. TangoNOW

- Region: 전국
- URL/Target: [app](https://ktnow.kr/) · [Firestore list](https://firestore.googleapis.com/v1/projects/ktangoguide/databases/(default)/documents/events?pageSize=300)
- Type: COMMUNITY · Recent Event: YES · Upcoming: 40 · Score: **38/45** · Decision: **ADD_NOW**
- Reason: 부산을 포함한 전국 원천성과 최근 갱신량이 가장 좋다. 공개 Firebase rule, 77-page variable pagination, 포스터 의존을 운영 모니터링한다.

### 7. Milonga Sueño Dulce mirror

- Region: 서울/La Ventana
- URL/Target: [public mirror feed](https://www.events1000.com/KR/Seoul/1084207278362147/Milonga-Sue%C3%B1o-Dulce)
- Type: ORGANIZER mirror · Recent Event: YES · Upcoming: 0 explicit · Score: **34/45** · Decision: **MONITOR**
- Reason: 2026-08-09까지 날짜·시간·주소·fee가 매우 좋지만 Facebook mirror다. primary source로 세지 않고 다시 갱신될 때만 보조 수집을 검토한다.

### 8. Social Dance Live

- Region: 부산/전국
- URL/Target: [Busan Tango query](https://www.socialdancelive.com/?genre=tango&location=Busan&sort=latest)
- Type: DIRECTORY · Recent Event: YES · Upcoming: 0 · Score: **33/45** · Decision: **ADD_LATER**
- Reason: 2026-08-23 Milonga R&D의 명시 날짜/장소를 확인했다. query 결과가 혼합 장르이고 현재 future coverage가 없어 재활성화 때 추가한다.

### 9. Korea Milonga Google Site

- Region: 전국 구조, 확인 페이지는 부산
- URL/Target: [Busan Sunday](https://sites.google.com/view/tangomilongaincorea/where-are-you-now/busan/sunday)
- Type: DIRECTORY · Recent Event: UNKNOWN · Upcoming: 0 dated · Score: **31/45** · Decision: **MONITOR**
- Reason: 주소·정기 시간·fee가 HTML에 있지만 현재 public calendars와 시간이 충돌한다. venue alias seed 외에는 최신 검증 없이 사용하지 않는다.

### 10. EnjoyTango Milonga Orange

- Region: 서울/Andante
- URL/Target: [Milonga Orange record](https://www.enjoytango.com/en/app/show.php?aid=1021)
- Type: DIRECTORY · Recent Event: UNKNOWN · Upcoming: 0 dated · Score: **31/45** · Decision: **MONITOR**
- Reason: 반복 요일·시간·장소·요금이 명확하고 HTML 추출이 쉽다. 게시일과 특정 행사 날짜가 없어 event source보다 venue enrichment source에 가깝다.

## 12. TOP 3 IMMEDIATE

### 1. `SRC-W-002` — TangoNOW Firestore REST

전국 및 부산의 원천성이 가장 좋다. list, document detail, 최근 생성 시각, 날짜·시간·장소, 비로그인 GET, robots 공개 경로를 모두 직접 확인했다. 빈 `price`, image-heavy records, pagination token과 public rule 변화를 방어해야 한다.

### 2. `SRC-W-003` — Tango Calendar Korea API

가장 쉬운 structured ingestion이다. list와 UUID detail이 모두 공개 JSON이고 날짜·시간·장소·요금·created/updated가 있다. 746개 raw record 중 과거 비율이 높으므로 cutoff, recurrence override, 취소 여부 처리가 필요하다.

### 3. `SRC-W-004` — DanceInfo public HTML

TangoNOW/Tango Calendar와 다른 공급 경로이며 경기·대전·전남까지 보완한다. date list와 detail 모두 SSR이고 fee가 좋다. robots상 `/api/`는 금지이므로 오직 `/lessons` HTML을 사용하고 `genre == 탱고`만 통과시킨다.

### Why not the other high scorers first?

- KCCTF는 최고 품질의 공식 source지만 연 1회성이라 상시 source 3개 뒤에 둔다.
- Miltang과 Tangodori는 구현하기 쉽지만 TangoNOW와의 관측 중복이 커서 v0.82 첫 3개에 동시에 넣으면 신규 coverage보다 중복량이 더 크게 늘 수 있다.

## 13. Regional Coverage Gap

| Region | Current best candidate | Verified upcoming | Gap |
|---|---|---:|---|
| 서울 | Tango Calendar / TangoNOW | 20+ to 27+ | 양호. source 간 중복이 가장 큰 문제 |
| 부산 | TangoNOW / Tangodori / Cafe de Tango | 18 on Tangodori; 3 TangoNOW records in full set | 공식 카페 상세 로그인; public primary 부족 |
| 인천/경기 | DanceInfo / Tangodori Seongnam | 4+ checked in 경기, 1 in Seongnam | 인천의 순수 탱고 공지는 희소; 혼합 라틴 행사 오탐 주의 |
| 대전 | Tangodori / DanceInfo | 11 / current monthly schedule | 공식 organizer 독립 site가 없음 |
| 대구 | Tangodori | 6 | 단일 aggregator 의존 |
| 광주 | Tangodori | 3 | CON/SUNCONMIL의 공식 공개 페이지를 찾지 못함 |
| 강원/춘천 | KCCTF | 6 festival sessions | 상시 weekly coverage 부족 |
| 청주 | Tangodori | 1 | 단일 aggregator 의존 |
| 전남/순천 | DanceInfo | 1 named future festival seen | official source 추가 확인 필요 |
| 제주 | Tangodori | 0 | 사실상 공백 |

## 14. Reverse Lookup of Known Venue Names

| Name | Official/public finding | Best usable target | Result |
|---|---|---|---|
| PISTA | standalone official event board not found | [Miltang PISTA detail](https://www.miltang.com/milongas/731), [Tistory venue article](https://itseemstobe.tistory.com/entry/%ED%83%B1%EA%B3%A0-%ED%94%BC%EC%8A%A4%ED%83%80-%EB%B0%80%EB%A1%B1%EA%B0%80-%EC%95%88%EB%82%B4) | aggregator + static article |
| La Ventana | no standalone official board found | [Sueño Dulce mirror](https://www.events1000.com/KR/Seoul/1084207278362147/Milonga-Sue%C3%B1o-Dulce), [venue article](https://itseemstobe.tistory.com/entry/%ED%99%8D%EB%8C%80-%EB%9D%BC%EB%B2%A4%EB%94%B0%EB%82%98-%EB%B0%80%EB%A1%B1%EA%B0%80) | monitor mirror |
| EnPaz Tango Studio | Naver Cafe `novatango` found, robots blocked | [Tango Calendar detail](https://tangocalendar.kr/api/events/2c88fdb1-ef6d-43df-9825-74490b75796d) | public API preferred |
| Tango Andante | Facebook link exposed by directories; no standalone board | [Tango Calendar event](https://tangocalendar.kr/api/events/3aa58986-65da-41c4-8693-895b005d1f1c), [venue article](https://itseemstobe.tistory.com/entry/%ED%83%B1%EA%B3%A0-%EC%95%88%EB%8B%A8%ED%85%8C-Tango-Andante) | public API preferred |
| Tango O Nada | `milonga.kr` found but blank | [DanceInfo O Nada event](https://danceinfo.net/lessons/3863), [GetBailar venue](https://getbailar.com/venues/tango-o-nada-i-seoul) | DanceInfo preferred |
| 아미고스튜디오 | official Daum Cafe found; detail login | [Daum home](https://cafe.daum.net/_c21_/home?grpid=1ZUn3), [Miltang La Vida](https://www.miltang.com/milongas/840) | Miltang secondary |
| 데땅고 | official Daum Cafe found; detail login | [Daum home](https://cafe.daum.net/_c21_/home?grpid=1Huyc) | monitor only |
| OCHO | standalone board not found | [OCHO schedule article](https://itseemstobe.tistory.com/entry/%ED%99%8D%EB%8C%80-%EB%B0%80%EB%A1%B1%EA%B0%80-%EC%A0%95%EB%B3%B4), Tango Calendar API | API preferred |
| K-TANGO | existing source confirmed | [existing target](http://www.k-tango.net/cnf/festival02/index.jsp) | keep `SRC-W-001`; no new ID |

## 15. Recommended Next Source IDs

| Proposed ID | Source | Exact collection target | Role |
|---|---|---|---|
| `SRC-W-002` | TangoNOW | `https://firestore.googleapis.com/v1/projects/ktangoguide/databases/(default)/documents/events?pageSize=300` | nationwide primary registry |
| `SRC-W-003` | Tango Calendar Korea | `https://tangocalendar.kr/api/events` and `/api/events/{uuid}` | structured calendar with fee |
| `SRC-W-004` | DanceInfo | `https://danceinfo.net/lessons?date=YYYY-MM-DD&genre=all&category=all&location=all` and `/lessons/{id}` | independent SSR regional supplement |

이번 조사에서는 DB 등록, collector 수정, scheduler 변경, 배포, 실제 수집을 수행하지 않았다.

## 16. Raw URLs / Notes

### Public list/API targets

- `https://firestore.googleapis.com/v1/projects/ktangoguide/databases/(default)/documents/events?pageSize=300`
- `https://firestore.googleapis.com/v1/projects/ktangoguide/databases/(default)/documents/milongas?pageSize=300`
- `https://tangocalendar.kr/api/events`
- `https://tangocalendar.kr/api/events/{uuid}`
- `https://tangocalendar.kr/api/venues`
- `https://danceinfo.net/lessons?date=YYYY-MM-DD&genre=all&category=all&location=all`
- `https://danceinfo.net/lessons/{id}`
- `https://www.miltang.com/milongas?week=YYYY-MM-DD&date=YYYY-MM-DD&region_id=N`
- `https://www.miltang.com/milongas/{id}`
- `https://tangodori.com/ko/{city}-milongas`
- `https://tangodori.com/ko/events/{id}`
- `https://kcctf.org/ko`

### robots notes

- `ALLOW`: Tango Calendar Korea, KCCTF, Dulce y Leo, Kakao Channel.
- `NONE` on API host: `firestore.googleapis.com/robots.txt` returned 404; the related app host `ktnow.kr` is `PARTIAL` with only `/admin/` disallowed.
- `PARTIAL`, target allowed: TangoNOW app, DanceInfo public HTML, Miltang, Tangodori generic UA, Korea Tango Cooperative, Daum Cafe public paths, Social Dance Live, Google Sites, Milongas-in, Tistory, Blogspot, Events1000/Glartent, GetBailar, Maily.
- `BLOCKED`: Naver Cafe (`User-agent: *; Disallow: /`).
- `NONE` or invalid: `milonga.kr`, `seoultango.com`, `tango.bien.ltd`, EnjoyTango. Absence is not permission; production onboarding should recheck.
- Tangodori blocks named GPTBot/ClaudeBot/etc. A production collector must use a truthful DanceMate UA, respect rate limits/content policy, and revalidate robots before onboarding.

### Major Risks

- Public Firebase/API rules can change without notice; monitor 401/403/schema drift.
- TangoNOW and Tango Calendar raw stores are past-heavy. Date filtering must happen before OCR or expensive parsing.
- Posters remain important, especially TangoNOW, Miltang, DanceInfo and cafes. Keep v0.81.3 OCR fallback, but prefer text/JSON fields first.
- Overnight times use `03:00` or even `28:30`; normalize end date without corrupting the organizer's original time.
- Recurring templates may conflict with one-off overrides/cancellations. Explicit dated override wins.
- Facebook mirrors can disappear or lag and must never be treated as an independent primary source.
- Official venues frequently publish only on social platforms or login-protected cafes, leaving 부산·광주·대구 official-source gaps.
- Mixed dance directories can create Salsa/Bachata false positives; accept only an explicit Argentine Tango/Tango genre or verified milonga semantics.

## 17. v0.82.4 Status Update — what this research actually became

Sections 1-16 above are the original research snapshot and are left
unchanged. This section records what the DB, the region master and the
collector code actually did with it, per source (`docs/
tango_source_application.csv` carries the same mapping in machine-readable
form).

| Candidate (this doc) | Decision | Current state |
|---|---|---|
| TangoNOW | ADD_NOW | **REGISTERED** - `SRC-W-002`, enabled |
| Tango Calendar Korea | ADD_NOW | **REGISTERED** - `SRC-W-003`, enabled |
| DanceInfo | ADD_NOW | **REGISTERED** - `SRC-W-004`, enabled |
| Miltang | ADD_NOW | **REGISTERED** - `SRC-W-005`, enabled |
| Tangodori (all 7 city variants + Jeju) | ADD_NOW / MONITOR | **REJECTED** - Section 12/36 of the v0.82.4 task: `docs/tango_aggregator_analysis.csv`'s own finding is unchanged, its Terms (updated 2026-06-27) explicitly prohibit "scrape or abuse the APIs" regardless of data quality or robots.txt. No collector, no Source row. |
| 2026 Chuncheon International Tango Festival (KCCTF) | ADD_NOW | **VALIDATED, NOT REGISTERED** - re-checked live 2026-09-06: robots `Allow: /`, Terms (a participant payment/refund policy, not a data-use restriction) has no scraping prohibition, the 10/3-10/5 program schedule is real and current. Not implemented this release: the visible SSR HTML only carries Day 1's program panel - Day 2/3 are present only inside the page's Next.js App Router RSC streaming payload (`self.__next_f.push(...)`), a materially more fragile format than the single `__NEXT_DATA__` blob `danceinfo_discovery.py` already parses. Building and trusting a parser for that format was judged out of scope for one annual, three-day event within this release - a wrong date/time for a real festival is a worse outcome than no coverage. Left as a documented candidate for a future release, not force-implemented to hit a source count. |
| Everything else in Section 7-9 (ADD_LATER/MONITOR/REJECT) | as scored | **NOT REGISTERED** - re-confirmed nothing here changed the original research's own reasoning (login walls, stale content, mixed-genre noise, or a Facebook-mirror provenance the project's own rules already exclude as a primary source) |

Regional coverage (Section 13 above) also moved, via the *existing* Miltang
source's own real data rather than any new source: 청주, 진주, 창원, 포항,
울산, 대구, 제주, and a 성남/분당 (경기) event are now real, currently-
collected items (see `docs/TANGO_SOURCE_IMPLEMENTATION.md`'s "v0.82.4"
section for the exact per-city evidence and root-cause diagnosis). Pohang's
and Daegu's own Miltang items exist but currently produce zero engine
candidates - a separate, out-of-scope extraction gap, not a region-master or
source problem.

TANGO SOURCE DISCOVERY COMPLETE
