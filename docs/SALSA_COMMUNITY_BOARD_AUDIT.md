# Salsa Community Board acquisition audit (2026-09-16)

Production `community_genres` identifies 17 Salsa-linked Communities. This is
the full inventory, not a hard-coded Source shortlist. Public Cafe home pages,
their iframe-backed menu/list pages and recent ordinary article rows were opened
without a signed-in session. Daum's robots.txt explicitly allows `/_c21_/home`,
`/_c21_/bbs_list` and `/_c21_/bbs_read`; Naver Cafe's robots.txt disallows
`/` for `*`, so Naver Cafe direct crawling is excluded. A board title can give
date/identity even when its detail body is blocked; time, fee and venue must
then remain unknown unless independently evidenced.

| ID | Community | Region | Homepage | Access / classification | Board / evidence |
|---:|---|---|---|---|---|
| 1 | 홍대 라틴로드 | 서울 | https://cafe.daum.net/salsai | PUBLIC / INACTIVE event board | `VocN` latest event notice Nov 2025; newer non-event home activity is not Event yield |
| 3 | 라틴속으로 - 살사 | 서울 | https://cafe.daum.net/intothesalsa | PUBLIC / BOARD_SOURCE_READY | [강습게시판 `dgfZ`](https://cafe.daum.net/_c21_/bbs_list?grpid=1XBze&fldid=dgfZ); [dated Oct 3 Salsa class](https://cafe.daum.net/intothesalsa/dgfZ/944) has public full body with date/time, location only “홍대 인근 연습실”, 9만원 course fee |
| 6 | 인천살사 동호회 엘마르 | 인천 | https://cafe.daum.net/clubelmar | PUBLIC / BOARD_SOURCE_READY (title; detail limited) | [월별 파티 `ew3I`](https://cafe.daum.net/_c21_/bbs_list?grpid=1Wcra&fldid=ew3I), [Sep 26 anniversary party](https://cafe.daum.net/clubelmar/ew3I/787); [금요 소셜 `eNy0`](https://cafe.daum.net/_c21_/bbs_list?grpid=1Wcra&fldid=eNy0); direct detail 403, no login bypass |
| 9 | 서귀포 살사동호회 | 제주 | https://cafe.daum.net/spasoapaso | PUBLIC / BOARD_SOURCE_READY (title; detail limited) | [정모·벙개 `AqxN`](https://cafe.daum.net/_c21_/bbs_list?grpid=1Ypx5&fldid=AqxN), [Sep 19 정모](https://cafe.daum.net/spasoapaso/AqxN/271), [Sep 17 번개](https://cafe.daum.net/spasoapaso/AqxN/270); detail 403 |
| 10 | 살사베이시스 | 서울 | https://cafe.daum.net/buls1004 | PUBLIC / INACTIVE | home latest visible Apr 2026, current event-bearing board not confirmed |
| 12 | 살사포유 | 서울 | https://cafe.daum.net/Salsa4U | PUBLIC / SEARCH_SOURCE_READY | [공지 `RT5f`](https://cafe.daum.net/_c21_/bbs_list?grpid=11Fg6&fldid=RT5f), Aug 31 “886회 정기모임 공지”; event date not established, detail blocked |
| 18 | 수라댄 | 경기 | https://cafe.daum.net/dk2094 | PUBLIC / BOARD_SOURCE_READY (title; body image-heavy) | [공지 `5YUX`](https://cafe.daum.net/_c21_/bbs_list?grpid=1SvB&fldid=5YUX), [Sep 18 한가위 파티](https://cafe.daum.net/dk2094/5YUX/1114) and [Sep 16 수요정모](https://cafe.daum.net/dk2094/5YUX/1113) have exact title dates |
| 20 | 일산살사동호회 | 경기 | https://cafe.daum.net/ilsan-salsa | PUBLIC / INACTIVE event board | [금요정모 `jLk0`](https://cafe.daum.net/_c21_/bbs_list?grpid=1WJVb&fldid=jLk0) latest Aug 2020; recent home posts do not make this board current |
| 22 | 보스톤 | UNKNOWN | https://cafe.daum.net/latinboston | PUBLIC / NO_EVENT_CONTENT confirmed | latest home post Jul 2026; no current event board evidence; name must not imply US or local region |
| 25 | 살사로 | 서울 | https://cafe.daum.net/salsaro | PUBLIC / INACTIVE event board | [정모장소 `INCp`](https://cafe.daum.net/_c21_/bbs_list?grpid=16tNe&fldid=INCp) only 2020/2016 items |
| 26 | 클럽 카디즈 | 경기 | https://cafe.daum.net/cadizdancestudio | PUBLIC / NO_RECENT_SALSA_EVENT | [공지+정모+행사 `Y0Wh`](https://cafe.daum.net/_c21_/bbs_list?grpid=1ZBmr&fldid=Y0Wh) recent Sep 17 Bachata/Kizomba class; do not copy Community Salsa genre to that post |
| 27 | 아임살사 | 경기 | https://salsa.nm2.co.kr | PUBLIC / INACTIVE | generic HTML site and robots allow normal pages; latest visible class May/June 2026, no upcoming Sept evidence |
| 29 | 진주 라틴 피루나 | 진주 | https://cafe.naver.com/jinjulatin | SEARCH_ONLY / ACCESS_LIMITED | homepage opened; Naver Cafe robots `Disallow: /`; use existing public Search API only if event evidence available |
| 30 | 전주살사 바차타 라틴크루즈 | 전북 | https://cafe.naver.com/jueonjuinsalsa | SEARCH_ONLY / ACCESS_LIMITED | homepage opened; Naver Cafe robots `Disallow: /` |
| 33 | 여수 엘카리베라틴클럽 | 전남 | https://cafe.naver.com/lusalsa | SEARCH_ONLY / ACCESS_LIMITED | homepage opened; Naver Cafe robots `Disallow: /` |
| 34 | 라틴아미고스 | 인천 | https://cafe.daum.net/AmigoS | PUBLIC / BOARD_SOURCE_READY | [공지 `MANg`](https://cafe.daum.net/_c21_/bbs_list?grpid=w40N&fldid=MANg), [Sep 16 Salsa 정모](https://cafe.daum.net/AmigoS/MANg/132) public full body states 7pm onward and 부평생활문화센터 연습실1 |
| 37 | 왕초보 환영 살사댄스 모임 | 서울 | https://www.daangn.com/kr/group/%EC%99%95%EC%B4%88%EB%B3%B4-%ED%99%98%EC%98%81-%EC%82%B4%EC%82%AC%EB%8C%84%EC%8A%A4-%EB%AA%A8%EC%9E%84-zweh2bwxa363/ | ACCESS_LIMITED | Daangn robots disallow group path for retrieval bots; no direct acquisition |

## Source preview

Primary metro boards: Community 34 `MANg` (full detail), 3 `dgfZ`
(dated classes, full detail), 18 `5YUX` (date in title; image-heavy), 6
`ew3I` (date in title; detail blocked). Community 9 `AqxN` fills a Jeju gap.
Existing Source `SRC-D-020` for ElMar is a **search API source**, not a direct
board; keep its evidence as secondary and use the official direct board as
primary if its event is independently verifiable. Existing disabled 수라댄
Source may be reused after config/URL preview instead of creating a duplicate.

Initial backfill: newest list page, ordinary articles only, up to 60 days old.
`(source_id, external_id)` is the existing incremental uniqueness contract;
unchanged posts do not spawn a new source_item. Relative dates anchor to the
post timestamp. A “매주” notice produces at most one occurrence in its posted
week, never an open-ended future series. Full-body content remains in the
existing acquisition/review flow. No collector creates a Venue.
