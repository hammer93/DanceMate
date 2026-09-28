# DanceMate

DanceMate는

> "오늘 춤추고 싶은 사람이
> DanceMate를 보고 실패 없이 갈 곳을 찾는 것"

을 목표로 하는 Dance Event Information Service다.

## 현재 상태

- Product Runtime: v0.96.23 (**같은 시각의 서로 다른 두 파티는 두 개의 Event다.**
  2026-10-03 토요일 21:00에 살사 파티가 두 개 있었다 — event 1603334 `모두의 라틴
  바차타 워크숍 및 살사 파티`(장소 **광주 J 라틴**, DJ 버퍼링, 21:00~01:00)와 event
  1603338 `검단 라틴솔 동호회 10월 미니파티`(장소 **단춤**, 인천 검단구 완정로7번길 1
  단춤스튜디오 B1, DJ 바밤바, 21:00~23:30, 1만원). 약 300km 떨어진 서로 다른 행사인데
  하나로 접혀서 그 중 하나는 **아무에게도 보이지 않았다**. 2026-09-25 21:00에도 같은
  일이 있었다(서울 강남 `클럽 라틴` vs 대구 `바바루`). 원인을 코드로 확정했다:
  `duplicates.classify()`의 auto-merge는 날짜·장소·시작시각 **세 가지 전부**를 요구하고,
  날짜와 시각만으로는 두 파티를 구분할 수 없다는 게 장소가 거기 있는 이유다. 그런데
  `_place()`는 장소를 "resolved `venue_id` **또는** 동일한 `venue_text` 문자열"로 읽었다.
  두 Event 모두 `venue_id` NULL, `venue_status` UNRESOLVED이고 문자열이 둘 다
  `스스 me1`이어서 `_place()`가 양쪽에 `text:스스me1`을 답했고 규칙이 발동했다
  (`event_duplicate_decisions` 1186, `SAME_DATE_VENUE_TIME`). `스스 me1`은 **두 본문
  어디에도 없다**. 두 본문은 장소를 그대로 적고 있고("장소 단춤", "장소 광주 J 라틴")
  `extract_venue()`는 둘 다 읽지 못한다(label 패턴이 요구하는 콜론이 없다). 그 문자열은
  poster 이미지에서 왔고 엔진이 출처를 정확히 기록해 두었다 — `field=venue`,
  `raw_text=@ 스스 me1`, `evidence_type=IMAGE_OCR`, `inference=.../posters/4588/...jpg`.
  **같은 poster URL**이 두 candidate의 venue를 공급했고, 8개 날짜·여러 도시에 걸쳐
  **총 18개 candidate**가 같은 값을 받았다. 누군가의 poster 하단 Instagram 핸들이
  장소로 읽힌 것이다. 이번 릴리스는 그 잘못된 venue 자체를 고치지 않고(다음 목표),
  그것이 **Event 하나를 잃게 만든 규칙**을 고친다: auto-merge는 이제 양쪽 모두
  **resolved된** Venue Master 행을 요구한다. 동일한 unresolved 문자열은
  `SAME_DATE_UNRESOLVED_VENUE_TIME`으로 **사람에게 가는 질문**이 되며, 이 모듈이 원래
  해결할 수 없는 것에 대해 해 온 그대로다. 이를 "서로 다른 행사라는 증거"로 취급하지
  **않는다** — 하나의 밀롱가를 다룬 두 post가 unresolved venue를 똑같이 적는 일은 흔하다.
  `_place()` 자체는 손대지 않았으므로 representative-source 적격 판정
  (`_place_and_clock_agree`)은 이전과 동일하다. 규칙만 고치면 이미 접힌 행은 영원히
  접힌 채로 남으므로, `scan()`이 `_release_stale_auto_merges()`로 시작한다: 현재 규칙이
  더는 auto-merge하지 않을 `AUTO` fold를 모듈 자신의 `record_decision(DISTINCT, AUTO)`
  경로로 해제한다(audit 행, `listing_state` 복구, representative 재선출) —
  `venue_resolution._release_automatic_duplicates()`가 merge의 근거였던 venue가 사라질 때
  이미 하던 것과 같다. 사람의 판단은 다시 묻지 않는다. **discriminator를 추측하지 않고
  Production의 fold 66 group·75 folded row 전수에서 측정했다**: place-must-be-resolved는
  2행 분리(false merge 2건 수정, true duplicate **0건** 파괴), 다른 DJ 3행(1건 파괴),
  다른 end_time 5행(4건 파괴), same-source-different-item 11행(9건 파괴), 다른 title
  27행(**25건 파괴**), 다른 fee 0행, 다른 source 64행(역방향). 운이 아니라 구조다 —
  **66 group 중 64개가 모든 member의 venue를 resolved로 가진다**. 그렇지 않은 2개가
  바로 두 false merge다. Offline simulation(컨테이너에 새 모듈을 올려 843행 read-only):
  kept folded 73, RELEASED 2, human fold 0, new auto merge 0, canonical A→B 변경 0,
  group merged 0, group split 2. 보호 관계는 새 규칙에서도 `auto=True` — `88436→221245`,
  `1392910→144289`, `1425406→144289`. 사용자 가치: visible 757→759, upcoming 113→114,
  TODAY 7→7, Salsa upcoming 27→28, Tango/Swing/Bachata 불변. duplicate 증가가 아니라
  **숨겨져 있던 서로 다른 Event의 복원**이다. 다음 목표는 그 잘못된 venue 자체다:
  엔진 `_image_venue()`가 evidence `inference`가 `LABEL:`로 시작하면 통과시키는데
  `extract_venue()`의 `@handle` 분기가 `label="@"`를 보고하므로 `LABEL:@`가 "`장소:`
  label만"이라는 v0.84.3의 의도를 빠져나간다. 그건 엔진 변경이라 ENGINE_VERSION bump와
  re-extract가 필요하고, 2,500행 재독을 canonical graph 변경에 섞으면 위의
  predicted-vs-actual 비교를 검증할 수 없게 되므로 이번에 넣지 않았다. ENGINE_VERSION은
  **1.05 유지** — 변경은 전부 `runtime/duplicates.py`(canonical resolver)와
  `scheduler/jobs.py`의 출력 한 줄이고, 엔진은 `canonical_event_id`·`venue_status`·Venue
  Master를 알지 못한다(엔진은 venue **문자열**을 낼 뿐이고 그것이 장소인지는
  `runtime.normalization.resolve_venue()`가 `venue_aliases`로 판단한다). 추출·분류·날짜·
  시각·venue·fee·identity_key 규칙이 하나도 바뀌지 않았으므로 2,543행을 다시 읽은 척하지
  않는다. re-extract는 필요하지도 않고 돌리지도 않았다 — fold graph는 언제나
  `duplicates.scan()`으로 끝나는 `event-normalization` job으로 수렴한다. migration 043
  유지 — `rule` 컬럼은 값 제약 없는 `TEXT`다)
- Product Runtime: v0.96.22 (robots.txt를 **정의된 대로** 읽는다. 이번 릴리스는
  robots 우회가 아니라 **판정 정확성** 수정이고, 방향이 예상과 반대였다. 프롬프트
  가설은 "`Sitemap:` 뒤의 `Disallow:`가 무시되어 접근 가능한 source가 잘못
  `FETCH_BLOCKED`된다"였는데, fixture 4개로 반증됐다: `Allow: /` + `Disallow:
  /private/` 조합은 **Sitemap 줄이 있든 없든** 똑같이 `/private/`를 허용하고, 두 줄의
  순서를 바꾸면 거부한다. 즉 Sitemap은 무관하다. 실제 결함은 두 개이고 배포 대상
  Python 3.12과 3.14 양쪽에서 재현했다. (1) **우선순위가 파일 순서다** —
  `Entry.allowance()`가 첫 매치에서 멈춘다. RFC 9309 §2.2.2는 **가장 긴 매치**가
  이기고 동점이면 덜 제한적인 쪽이 이겨야 한다. 그래서 `Allow: /`를 위에 쓰면 그
  아래 `Disallow: /api/`가 무력화된다. (2) **와일드카드 미지원** —
  `RuleLine.applies_to()`가 `startswith`뿐이고 생성자가 패턴을 percent-encode해서
  `Disallow: /?*&type=`이 `/?%2A&type=`이라는 리터럴이 된다(이 프로젝트가 실제로
  읽는 13개 robots 파일 중 2개가 패턴 안에 `*`를 쓴다 — socialdancelive 6건,
  sidf.kr 80건). 세 번째로 의심했던 "query-string 규칙은 매치 불가"는 **사실이
  아니었다**(`Disallow: /?genre=` 단독은 정상 차단). 그래서 이 버그는 잘못 막는
  방향이 아니라 **잘못 허용하는 방향**으로만 작동했다. 등록 source 49개·origin
  18개·acquisition이 실제 요청하는 URL 1,148개 전수 비교 결과: ALLOW→ALLOW 745,
  BLOCK→BLOCK 402, **ALLOW→BLOCK 1**, **BLOCK→ALLOW 0**. 즉 잘못 막힌 source는
  하나도 없고, 새로 열리는 것도 없다. 유일한 변경은 활성 source `SRC-W-008`
  (Social Dance Live)의 `?genre=salsa&type=posters` 경로인데, 그 사이트가 `Disallow:
  /?genre=`와 `Disallow: /?*&type=` 두 번에 걸쳐 거부하는 경로다. 한 경로만이
  아니라 그 파일이 막는 **13개 경로**(`/admin`, `/auth`, `/create`, `/my`, 모든 필터
  query)가 전부 "허용"으로 답해지고 있었다. 실무적 영향은 없다고 정직하게 적는다:
  SRC-W-008은 NAVER_WEB source로 Naver 검색 API로 발견하고 robots가 허용하는
  개별 `/posters/...` 페이지를 가져오므로, 저장된 5건·event 3건·body는 그대로다.
  브리프가 지목한 `latindancekorea`는 **애초에 등록된 source가 아니어서** 막힌 적도
  열린 적도 없고, 교정 후에는 오히려 더 제한적이다 — HTML(`/`, `/events`,
  `/events/<id>`, `/classes`)은 전후 모두 허용이고 `/api/`·`/admin/`·`/organizer/`가
  ALLOW→BLOCK이 된다(v0.96.20에서 내가 판단으로 피했던 `/api/events`를 이제 코드가
  스스로 막는다). 구현은 새 의존성 없이 `runtime/robots.py` 약 150줄이다(protego·
  reppy 등은 미설치이고 ARM64 보드 이미지에 의존성을 더하는 비용이 수정보다 크다):
  최장 매치 우선·동점은 덜 제한적 우선, `*`와 말미 `$` 와일드카드, 우리를 지목한
  group이 `*`보다 우선(단 `User-agent: Mozilla` group은 우리 것이 아니다 — HTTP
  헤더가 Mozilla 호환 문자열이므로 substring 매칭은 쓰지 않는다), 연속 `User-agent`
  줄은 한 group, 같은 agent의 group은 병합, `Sitemap`/`Crawl-delay`/미지의 field는
  group을 끊지 않고 무시, 빈 `Disallow:`는 아무것도 막지 않음, 주석·빈 줄·공백·
  대소문자 혼용 field(corpus에 445줄) 처리. **정책은 바꾸지 않았다**: robots.txt를
  읽지 못할 때의 401/403 거부, 그 외 4xx 허용, 5xx·네트워크 실패 허용을 그대로
  유지하고 status별 테스트로 고정했다. parsing 정확성은 crawling 정책이 아니다.
  parsing 외 유일한 동작 변화는 요청 헤더다 — `RobotFileParser.read()`가 `urlopen`을
  맨손으로 불러 robots.txt만 `Python-urllib`로 받고 있었는데, 페이지와 같은
  `DanceMate` 이름으로 요청한다(18개 origin 전부 status 동일 확인). ENGINE_VERSION은
  **1.05 유지** — robots 판정은 `runtime.acquisition`/`runtime.robots`에만 있고 엔진은
  둘 다 import하지 않으며 추출·분류 의미가 바뀌지 않았으므로, 2,543건을 다시 읽은
  척하지 않는다. migration 043 유지)
- Product Runtime: v0.96.21 (영문 월 + 같은 달 날짜 범위를 읽는다. `DATE_PATTERNS`의
  기존 8개 패턴은 전부 숫자형(`2026.10.08`, `9.18-20`, `10/8`) 또는 한글형
  (`10월 8일`, `9월 19,20일`)이라 **영어를 한 글자도 몰랐다**. 그래서 영문으로 날짜를
  쓰는 페이지는 틀린 날짜도 아니고 "배치 못 한 날짜"도 아니라 **아무것도** 만들지
  않았다: `_norm_date("DATE Oct 8-11, 2026")` → `(None, None, None)`.
  v0.96.20이 robots 허용 + 본문 1,070자 전체 수신까지 확인하고도 WATCH로 남겨 둔
  **SEOUL lindyfest 2026**(2026-10-08~11, BIG APPLE 서울)이 정확히 이 경우다.
  이번 릴리스는 문법 하나만 추가하고 **기존 multi-day 계약을 그대로 따른다**:
  v0.91.0 PHASE 5가 숫자형 `9.18-20`(BAL&HOP)에 대해 정한 대로 `event_date`는
  범위의 **첫째 날**이고, 전체 구간은 `MULTI_DAY_EVENT` context evidence
  (inference `DATE_RANGE_START_ONLY`)로 남긴다 — `events`에 end-date 컬럼이 없기
  때문이다. 날짜별 event로 쪼개지 않고, 끝 날짜를 만들어내지도 않는다. 지원 문법은
  `Oct 8-11, 2026` / `Oct 8–11, 2026` / `October 8-11, 2026` / `Oct. 8-11, 2026`와
  대소문자·공백 변형이며, 12개월 전체의 긴 이름·약어·마침표 형태를 모두 안다
  (`september`가 `sep`으로 잘리지 않도록 긴 것부터 매칭). 검증은 두 종류로 나뉜다:
  거꾸로인 범위(`Oct 11-8, 2026`)와 없는 날(`Feb 29-30, 2026`)은 "날짜를 썼지만
  배치 불가"로 raw만 남기고, 1~31 밖의 날(`Oct 0-4`, `Oct 8-99`)은 **매치 자체를
  하지 않아** 같은 글의 다른 실제 날짜를 뒤 패턴이 읽을 수 있게 둔다. 일반 단어 속
  월 이름(`May Dance Better`, `March Into Swing`, `Octoberfest 8-11`)은 월 이름이
  자기 날짜로 바로 이어져야 한다는 조건과 왼쪽 경계로 걸러진다. 새 패턴은
  **끝에서 두 번째**에 둔다 — `_norm_date()`는 패턴마다 글 전체를 검색해 첫 매치에서
  멈추므로, 앞에 두면 본문 뒤쪽의 영문 범위가 제목의 한글 날짜를 이긴다. 구현 전에
  Production corpus를 먼저 측정했다: 저장 본문·제목 2,535건과 저장 OCR 1,589건에서
  영문 월 토큰은 각각 20회/27회지만 **same-month 범위는 0건**이고, git-stash
  baseline diff 결과 **변경된 source_item은 0건**(날짜·시각·type·cardinality·분류·
  venue·요금·identity·fold·TODAY·upcoming 전부 0). 즉 기존 저장 row를 하나도
  건드리지 않는다. target을 실제 사용자에게 보이게 하려면 parser만으로는 부족해서
  (해당 source가 애초에 등록돼 있지 않아 저장 item이 0건이었다) SEOUL lindyfest
  공식 사이트를 기존 Admin gate로 WEB organizer source 1개만 등록했다. migration 043
  유지, ENGINE_VERSION은 **1.05**로 올렸다 — generic extraction 동작이 실제로
  변했으므로 저장 row 전체를 다시 읽는다. 범위 밖으로 남긴 것: cross-month
  범위(`Oct 30-Nov 2, 2026`)와 단일 날짜(`October 15, 2026`)는 반쯤 읽지 않고
  그대로 두고 다음 후보로 기록했다)
- Product Runtime: v0.96.20 (Salsa/Swing **direct source coverage expansion**.
  Source 개수를 늘리는 릴리스가 아니라, 실제로 읽을 수 있는 공개 게시판을
  등록하는 릴리스다. 먼저 이유를 찾았다: Swing은 등록 source 12개·활성 5개로
  이미 **406건**을 수집했는데 upcoming event가 **0건**이었고, 그 406건 중
  **346건이 Naver Cafe** 글로 전부 `ROBOTS_DISALLOWED`다(NAVER_CAFE 전체 814건 중
  본문 사용 가능 **0건**, 비바스윙 123 + 올어바웃스윙 223 포함). Salsa도 같은 벽에
  438건이 묶여 있다. 일부 Daum 게시판은 HTTP 200을 주면서 회원 전용이라
  `BODY_UNAVAILABLE`이다(스윙팩토리 24/24). 즉 한국 살사·스윙 씬은 일정을
  **우리가 읽어도 되지 않는 곳**에 주로 올린다 — 이건 우회하지 않고 BLOCKED로
  기록했다. 그래서 본문이 실제로 공개된 Daum 공개 게시판 3개만 활성화했다:
  SDA 홍대 정모·파티(SALSA, 서울, 90일 15건·본문 15/15·event 7건, 주 1회 공지 —
  기존 카페명 검색 경로는 총 10건/5 event였으므로 신규 등록이 아닌 **경로 교체**),
  네오스윙(SWING, 서울, 18건·본문 18/18·event 6건, 기수 졸업파티), 수원 린디성
  소셜(SWING, **경기**, 1건이지만 시간까지 있는 실제 소셜). 라틴파라다이스(강남)는
  공개 게시판이 전부 강습 모집글이어서 `EVENT_PRIMARY`로 읽으면 false event가
  2건 생긴다(제목의 `10월 31일 할로윈 파티`에서 날짜를, 본문의 매주 토요일 강습에서
  시간을 가져옴) — `CLASS_PRIMARY`로 등록하면 0건이 되는 것을 양방향 확인하고
  **disabled + MONITOR**로 남겼다. 등록은 모두 기존 `scripts/apply-board-sources.py`의
  admission gate(preview → `/test` PASS + items → enable → decision → readback)를
  그대로 통과했고, 이번에 script는 genre/platform/role/board 목록을 spec에서 읽도록
  최소 일반화했다(기존 SALSA spec은 바이트 단위로 동일한 config를 생성). parser·
  extraction·classification·identity·duplicate 규칙은 **하나도 바꾸지 않았다**.
  ENGINE_VERSION은 **1.04 유지** — engine 동작이 변하지 않았으므로 2,516건을
  재추출한 척하지 않는다. migration 043 유지. 못 가져온 것도 적어 둔다:
  SEOUL lindyfest 2026(10/8~11, BIG APPLE 서울)은 robots 허용·본문 전체 수신인데
  페이지가 `DATE Oct 8-11, 2026`이라고 써서 `extractor.DATE_PATTERNS`가 영문 월
  약어 + 일 범위를 읽지 못해 날짜가 안 잡힌다. 이건 source 문제가 아니라 generic
  engine gap이므로 이번 릴리스에 섞지 않고 다음 후보로 기록했다)
- Product Runtime: v0.96.19 (행사가 자기 시간 범위를 적어 놓아도, 근처에 수업
  단어가 있으면 그 범위를 버렸다. 가또땅고 3199의 `오픈특강 with 샤론y태희
  9:00pm-12:30am 밀롱가`는 밀롱가가 자기 시간을 말하는데 10분 먼저 끝나는
  오픈특강이 16글자 안 **앞쪽**에 있어서 범위가 통째로 탈락했고, 남은 시계가
  공연뿐이라 22:30이 저장됐다. 또도땅고의 낮 밀롱가는 `2:00pm ~ 4:00pm 밀롱가
  씨엠쁘레`인데 01:00으로 읽혔다. 이제 range에도 v0.96.18과 같은 질문을 한다 —
  수업 단어가 행사 자신의 단어보다 정말 더 가까운가. 다만 range의 영향 범위는
  lone clock과 비교할 수 없이 넓어서(본문 1,508건 + 저장된 poster OCR 891건 중
  205건이 현재 거부됨) 규칙 두 개가 함께 간다. (1) 행사 단어가 **다른 시계로
  바로 이어지면** 그 단어는 그 시계를 부르는 것이지 이 range를 부르는 것이
  아니다(4449의 `소셜 시작 : PM 8:00` — 이어지는 시계가 판정 대상 range 자신이면
  그 range의 라벨이므로 그대로 인정, 4415의 `파티 시간: P.M 9:00 - A.M 1:00`).
  (2) 수업 단어가 range **뒤**에 오면 그 range의 라벨이므로 행사 단어가 더
  가깝더라도 여전히 그 수업의 것이다(피스타 poster의
  `심야밀롱가(11:30 p.m-4:30 a.m) 패키지`는 심야 패키지 시간이지 밀롱가 시간이
  아니다). 단순 거리 비교는 205건 중 8건을 통과시키고 그중 2건이 오류인데, 두
  규칙이 각각 하나씩 막아 6건만 남는다. 행사 단어가 여러 range를 부를 때는
  위치가 아니라 **가장 가까운** range가 이긴다(`공연 오후 8시~8시30분 LATIN
  PARTY 오후 9시~12시`에서 파티가 공연의 30분을 가져갔다). 통과된 6건 중 3건은
  meridiem이 아예 없어(`9:00-1:00 소셜`, `9시~12시`) 오전으로 읽히므로
  `_readings()`가 다시 거부한다 — 밤 행사에 오전 9시를 광고하는 것은 아무것도
  광고하지 않는 것보다 나쁘다. classification·collector·acquisition·Event
  identity·Region·Source authority·중복/canonical·정규화 큐·venue·date 추출·
  `EVENT_WORDS`·`DATED_PROGRAM_WORDS`·OCR은 그대로다. migration 043 유지,
  engine 1.04: 전체 2,516건 중 **3건**만 바뀌어 전부 시각→시각, None→시각 0,
  시각→None 0, 날짜·cardinality·분류·venue·요금 변화 0, KET 회귀 0. 3건 모두
  이미 저장돼 있던 틀린 시각이 글이 말하는 시각으로 옮겨간 것이고, 셋 다 과거
  날짜라 TODAY recall은 움직이지 않는다. 가또땅고 3201은 2/22이 수업만 있는 날인데
  글이 `MILONGA_WITH_CLASS`로 분류돼서 전에도 후에도 수업 시간표를 읽는다 —
  분류 쪽 문제라 이번 범위 밖이고 테스트로 고정해 두었다)
- v0.96.18 (본문에 다른 프로그램의 시간 범위가 있으면 행사
  자신의 시작 시각을 읽지 못했다. BABARU의 `PM 8:00~9:00 (워크샵), PM 9:00
  START (소셜)`에서 워크샵이라는 단어는 9:00보다 **4글자 앞**, 소셜은 **1글자
  뒤**에 있는데 `_is_other_programme()`이 거리를 비교하지 않는 절대 veto라서
  후보가 전부 탈락했고, 21:00은 poster에서만 올 수 있었다. 홍턴 9/23은 그 날
  `파티` 제목이 시계 세 개 모두에 가까워 위치상 첫 번째인 워크샵 19:00이
  선택됐다(실제는 `소셜 오픈 오후 9시`). 이제 lone clock에 대해서만 **가까운
  단어가 이긴다**(동점은 다른 프로그램 승, 행사 단어가 아예 없으면 종전처럼
  절대 veto — `살사 워크샵 오후 7시~9시`는 그대로 None), 그리고 행사 단어가
  붙은 후보 중 **글이 "오픈/시작"이라고 말한 시계**가 위치보다 우선한다.
  거리 비교가 새로 통과시킨 오류 하나는 명시적으로 막았다: range의 끝은 시작이
  아니다(`9:00-1:00 소셜`은 01:00 시작이 아니다). range guard·`_is_other_
  programme()`·range 판정 규칙은 그대로다 — corpus 전체에서 range guard를
  지워도 바뀌는 것이 **없음**을 측정했다. migration 043 유지, engine 1.03:
  전체 2,504건 중 **4건**만 바뀌어 None→시각 2, 시각→시각 5, 시각→None 0,
  날짜·cardinality·분류 변화 0. 대상이 대부분 과거 날짜라 TODAY recall은
  움직이지 않는다. 가또땅고 3199은 여전히 틀렸다 — 같은 결함의 range 쪽이고
  이번 범위 밖이라 테스트로 고정해 두었다)
- v0.96.17 (날짜별 프로그램이 자기를 `LATIN NIGHT`라고만
  부르면 그 날짜가 Event가 되지 않았다. 홍턴 추석 run은 네 날을 나열하고 각
  날을 설명하는데 — 바차타 파티 / 키좀바 파티 / 살사데이 / `추석 이벤트 LATIN
  NIGHT ... 오픈 오후 9시` — 마지막 하나만 dated-program vocabulary가 모르는
  단어였다. 그래서 v0.96.15 guard 3이 제 역할대로 "지금 읽히는 날(26일)이
  살아남지 못한다"고 판단해 run 전체를 한 건으로 남겼고, 그 한 건은 시각도
  값도 23일 것(19:00, 20,000원)이었다. 이제 `DATED_PROGRAM_WORDS`가
  `night|나이트`를 읽는다 — `extract_schedule()`과
  `extract_day_list()` **두 곳에서만**. `EVENT_WORDS`는 건드리지 않는다:
  그것은 시각 range·단일 시각·요금·대표 segment 네 가지를 결정하고, LATIN
  NIGHT와 소셜이 함께 있는 글은 그것을 넓히면 소셜의 21:00 대신 NIGHT의
  19:00을 읽는다. classifier vocabulary도 넓히지 않는다 — 넓히면 무료 강습
  (3778 MAX NIGHT Free Salsa On1 Class)과 워크샵 본문(3803 LATIN NIGHTS)이
  Event가 되어 false positive 2건이 생긴다. 후기(342)·여행기(2417)·roundup을
  막는 것은 이 패턴이 아니라 classifier와 "날짜가 없다"는 사실이고, 테스트는
  그 실제 메커니즘을 검증한다 — migration 043 유지, engine 1.02: 전체 2,489건
  중 **1건**만 바뀌어 1→4 candidate, 날짜 3개 추가·0개 손실, 분류 변화 0.
  대상 네 날짜가 모두 과거이므로 TODAY recall은 움직이지 않는다)
- v0.96.16 (danceinfo.net은 한 공지가 여러 날 열리면
  **(글, 날짜)마다 별도 row**를 발행한다 — 부에나 추석 파티는 9/23~27의
  `idx` 27718~27722 다섯 줄이고, 그 다섯 날짜 페이지에 모두 실린다. 우리가
  `전체일정`으로 저장하는 필드가 바로 그 날짜 집합인데, `extract_schedule()`은
  그것을 **날짜 heading 여러 개**로 읽었다. 그러면 마지막을 뺀 모든 날짜가
  빈 segment가 되어 버려지고 마지막 날짜가 `일정정보`와 본문 전체를 삼키므로,
  다섯 밤짜리 파티가 **마지막 하루짜리 Event 하나**로 저장됐다. 이제
  `extract_day_list()`가 그 필드를 글이 적어 둔 날짜 목록으로 읽는다.
  "날짜가 여러 개 + 공통 일정 한 줄"이라는 **형식만으로는 근거가 되지 않는다**
  — live corpus에서 그 형식은 7번 중 1번만 맞고, 나머지는 바르셀로나 congress,
  제네바 festival, `6주과정 집중반`, `10월 스케줄` roundup이다. 그래서 다섯 개
  조건(source가 EVENT로 분류 / 자기 `전체일정` 필드 / course evidence 없음 /
  그 날 자기 문장이 공통 블록을 이긴다 / 지금 보이는 날짜와 시각을 잃지 않는다)을
  모두 hard gate로 둔다. 함께, 폐기된 `danceinfo_region` 경로로 저장된 19건을
  기존 acquisition 경로로 재취득했다 — 그 body의 `전체일정`은 연도가 없고
  payload에 없는 `수강료` 라벨이 붙어 있어서, 두 반쪽은 서로가 필요하다
  — migration 043 유지, engine 1.01: 전체 2,483건 중 6건이 바뀌고 날짜 10개가
  늘고 2개가 줄며(둘 다 이미 지난 날), 시각·분류·예정 Event를 잃는 곳은 없다.
  휴무일·워크샵만 있는 날·festival·roundup·영업안내는 그대로다.
  **Production이 보는 evidence를 harness도 봐야 한다**: body만 보던 harness는
  BABARU를 틀리게 읽었고, poster OCR까지 재현한 harness가 Production을
  1,368건 중 1,366건 재현한다)
- v0.96.15 (연휴 동안 문을 여는 클럽은 자기 날짜 목록을
  스스로 적어 두고(`전체일정 2026-09-24,2026-09-25,2026-09-26,2026-09-27`)
  그 날들을 하나씩 설명하는데, Production은 그 전체를 **하루짜리 Event 하나**로
  저장하고 있었다. 어느 하루의 Salsa/Bachata 누락 9건 중 8건이 이 모양이었고,
  전부 이미 실제 Event를 — 자기 기간 중 엉뚱한 하루에 — 가지고 있었다.
  danceinfo는 `published_at`을 일부러 비워 두므로 본문의 `9/25` 같은 날짜가
  아예 해석되지 않았고, `extract_schedule()`은 제목에 일정/공지가 있어야만
  동작했다. 이제 글이 스스로 연도까지 적어 둔 날짜 목록이 있으면 그 목록에
  한해 본문의 날짜를 읽고, 날짜별 프로그램이 있는 날만 Event가 된다
  — migration 043 유지, engine 1.00: 전체 2,472건 중 5건만 1→N으로 바뀌고
  날짜를 잃는 글은 하나도 없다. 4주 과정·주간 roundup·당첨자 발표·휴무일은
  그대로다)
- v0.96.14 (source가 "밤"으로 분류해 둔 글을 그 방향으로도
  읽는다. v0.96.10 이후 `sold_as_a_course()`는 danceinfo.net이 강습으로
  분류한 글에서만 그 category를 읽었고, 출빠정보·파티·정모로 분류한 글에서는
  아무도 읽지 않았다. 그래서 본문에 워크샵·무료강습이 있다는 이유만으로
  실제 밤 행사가 CLASS로 떨어졌다. site가 밤으로 분류한 52건 중 11건이
  candidate를 못 만들었고 그중 7건이 실제 밤이다 — migration 043 유지,
  engine 0.99: category는 보게 만드는 근거일 뿐 판정이 아니어서, 특정 날짜와
  시계라는 logistics를 함께 요구한다. 전체 2,468건 중 정확히 7건만 바뀌고
  모두 CLASS → SOCIAL_WITH_CLASS다)
- v0.96.13 (danceinfo.net 상세 페이지의 본문을 og:description
  (약 140자에서 `…`로 잘리는 미리보기)이 아니라, 그 페이지가 이미 싣고 있는
  Next.js payload에서 읽는다. 저장된 181건 중 162건이 잘린 미리보기였고,
  DanceInfo가 Event로 분류한 글 중 candidate를 못 만든 22건의 19건이 그것이었다
  — migration 043 유지, engine 0.98)
- v0.96.12 (danceinfo.net의 `genreName`은 `바차타/살사`처럼
  여러 장르를 한 문자열에 담는 복합 label인데, 이것을 `==`로 읽어서 "이 밤이
  *오직* 살사인가?"를 묻고 있었다. 살사 source는 봐야 할 120건 중 23건만
  보고 있었고, 나머지는 source_item조차 되지 못해 재추출로도 복구할 수 없었다.
  `genre_tokens()`가 `/`로 나눈 token 집합에 configured genre가 있는지 묻는다
  — migration 043 유지, engine 0.97 유지)
  - v0.96.11은 여행기·귀국 인사·협찬 공지를 행사로 읽지 않게 했고, v0.96.10은
    source가 이미 분류해 둔 강습 category를 버리지 않게, v0.96.9는
    FETCH_BLOCKED 항목의 본문 출처를, v0.96.8은 collector의 known_event_type
    위에 recap/공지 guard를 두는 순서를, v0.96.7은 과정 증거 판정을 고쳤다.
  - v0.96.6은 normalization이 "가장 최근 candidate 500개"만 보던 window를
    없앴고(migration 043), v0.96.5는 제목이 밤 행사를 선언하는 글이 본문의
    강습 언급 때문에 CLASS로 떨어지던 문제, v0.96.4는 "9월 19,20일" 형태의
    제목 날짜와 구역 표시 너머의 시계 문제, v0.96.3은 engine 버전이 올라간 뒤
    기존 본문을 작은 batch로 재추출하는 incremental 경로였다 (migration 042).
- Information Engine: v1.00 (`engine/`) — 글이 자기 날짜 목록을 연도까지
  적어 두고 그 날들을 하나씩 설명하면, 프로그램이 있는 날마다 candidate를
  만든다. 목록에 없는 날, 프로그램이 없는 날(휴무), 과정의 회차 날짜는
  만들지 않는다. 0.99까지의, source가 자기 글을 밤으로 분류해
  두었고, 그 글이 특정 날짜와 시계를 함께 싣고 있으며, 소셜·파티·정모를
  이름으로 부르면, 본문의 강습 언급이 그 밤을 덮어쓰지 못한다. 0.98까지의,
  제목이 밀롱가/쁘롱가/쁘락띠까를
  선언하고 그 제목이 스스로 강습을 파는 글이 아니며, 본문에 수강료·커리큘럼·
  개강 같은 과정 증거가 없고, 행사 logistics(시계 + 날짜/장소/입장료/DJ)가 있으면
  본문의 강습 언급이 그 행사를 덮어쓰지 못한다. 0.92까지의 제목 날짜 읽기,
  "@사람·계정"을 장소로 읽지 않는 규칙, 구조적 segment 분리는 그대로다
  (RELEASE_NOTES 참고).
- Initial Server: ROCKPro64 (PINE64 v2.1 / RK3399 / ARM64 / Debian 13)
- Region: 전국 - Region master가 서울/부산/대전/인천을 포함한 광역시·도 단위로
  확장됨 (실제 데이터가 있는 지역은 소스 수집 현황에 따라 다름)
- Genres:
  - Tango
  - Salsa
  - Swing
  - Bachata
  - Balboa
  - Kizomba

제품 버전과 Information Engine 버전은 서로 다르다. `VERSION`은 제품 런타임
버전이다. Engine은 v0.77에서 처음으로 추출 로직이 수정되어 v0.74가 되었다.
손대지 않은 import 상태는 `engine-v0.73-baseline` 태그에 남아 있다:

    git checkout engine-v0.73-baseline -- engine/src/extractor.py

Engine v0.76은 **연도 없는 날짜의 연도를 게시일에서 가져온다.** `9/25`는 그
글이 쓰인 시점 근처의 9월 25일을 뜻하므로, 게시일 전후 세 해 중 가장 가까운
해를 고른다. 12월 28일 글의 `1/3`이 다음 해 1월이 되는 것도, 2011년 글이
2011년에 머무는 것도 같은 규칙 하나다. 본문에 연도가 명시돼 있으면 그것이
언제나 이긴다. **게시일이 없으면 날짜를 만들지 않는다** — 빠진 날짜는 되돌릴 수
있지만 틀린 날짜는 사람을 엉뚱한 날 밖으로 내보낸다.

Engine v0.75는 탱고 밖의 소셜 댄스를 인식한다. 탱고는 자기 소셜 이벤트에
이름(밀롱가)이 있지만 살사·스윙은 그것을 `소셜`이나 `파티`라고 부른다. 단어만
찾으면 강습 광고까지 이벤트가 되므로, **소셜이 제목에 있거나 자기 시각 바로 옆에
쓰였을 때만** 근거로 인정한다. 강습+소셜 복합 공지는 소셜 쪽을 살리고, 소셜의
시간을 쓴다(강습 시간이 아니라).

## 현재 개발 우선순위

1. ~~Information Engine v0.73 baseline~~
2. ~~ROCKPro64 Persistent Runtime~~
3. ~~Real Source Data~~
4. ~~Human Verification~~
5. ~~DanceMate Alpha~~ (v0.77: search API + `/`, `/events`, `/events/{id}`)
6. Real User Feedback ← 다음

## 초기 Alpha 범위

Search
→ Event List
→ Event Detail

## Architecture

```
docker compose
├─ postgres    postgres:16-alpine    runtime state / scheduler heartbeat / job history
├─ runtime     dancemate/runtime     API + migration runner            :8080
└─ scheduler   dancemate/runtime     periodic worker (same image)
```

**Hybrid persistence.** The DanceMate Runtime uses PostgreSQL. The Information
Engine keeps its existing SQLite store, unchanged - v0.74 does not migrate the
engine's database. See `deploy/rockpro64/README.md` for why and how.

### Runtime API (LAN only, no authentication)

| Endpoint          | Purpose                                                      |
|-------------------|--------------------------------------------------------------|
| `GET /health`     | cheap liveness probe: `{"status":"ok","version":"0.96.23"}`      |
| `GET /version`    | product runtime version vs Information Engine version         |
| `GET /status`     | six components; HTTP 503 if any FAILs                         |
| `GET /status/summary` | the dotted operator report used by `check-server.sh`      |
| `GET /resources`  | CPU load, memory, disk usage                                  |

### Alpha user surface (LAN only, no authentication)

| Endpoint | Purpose |
|---|---|
| `GET /` | 오늘 갈 수 있는 곳 |
| `GET /events?when=today\|tomorrow\|weekend\|this_week\|upcoming` | 목록 |
| `GET /events/{id}` | 상세 + 출처 원문 링크 |
| `GET /api/events` | 같은 검색의 JSON. `when` / `date` / `from` / `to` / `genre` / `region` / `status` |
| `GET /api/events/{id}` | 이벤트 하나와 그것을 언급한 모든 게시글 |

`GET /`는 다섯 개 탭(행사/장소/동호회/정보원/게시판)을 공유하는 genre 필터로
넘나든다 — 장소·정보원은 한 줄짜리 목록, 동호회는 카드, 게시판은 관리자가 쓴
공지(NOTICE 보드)다. 각 탭은 `?genres=`로 같은 genre 선택을 유지한다.

날짜는 Asia/Seoul 기준. LIVE로 수집된 것만 노출한다 — snapshot과 fixture는
콘솔에만 남고 사용자에게 가지 않는다. 지난 행사와 취소된 행사는 기본 목록에서
빠지지만, 취소된 행사의 상세 페이지는 남는다 — 링크를 가진 사람은 취소 사실을
알아야 한다.

엔진의 상태 용어는 사용자에게 그대로 나가지 않는다: 확인됨 / 확인 필요 / 예정 /
정보 충돌 / 취소. 사람이 검토한 행사는 `관리자 확인`으로 따로 표시하며, 이는
엔진의 근거 게이트와 다른 것이다. 각 행사에는 원문을 마지막으로 읽은 시각이
표시되고, 오늘 행사인데 하루 이상 지났으면 `재확인 필요`가 붙는다.

### Admin console (LAN only, HTTP Basic)

`http://<board>:8080/admin` — Dashboard, Intake, Review, Events, Duplicates,
Sources, Venues, Organizers, Genres & Regions, Usage, System. Server-rendered;
credentials come from
`ADMIN_USERNAME` / `ADMIN_PASSWORD` in `.env`, and the console refuses every
request when no password is set. JSON equivalents live under `/api/admin/`.

Dashboard는 **오늘 할 일**로 시작한다 — 오늘 / 내일 / 이번 주 / 검토 대기 /
검토 완료 / 지난 행사, 그리고 바로 이어지는 다섯 개의 Review 필터. 수집 총계는
그 아래 Collection으로 내려갔다. 아침에 필요한 것은 총계가 아니라 오늘이다.

**Coverage** 패널은 장르 × 지역을 앞으로의 행사 기준으로 보여준다. 0인 칸이
요점이다 — 총계로는 부산 살사가 0이라는 사실이 보이지 않는다. 실제 공개 소스가
없으면 억지로 채우지 않는다.

**Alpha usage** 패널은 목록 열람 / 상세 열람 / 원문 이동 세 가지 횟수만
보여준다. IP·세션·사용자 식별자를 저장하지 않으며, 저장할 컬럼 자체가 없다.

Dashboard의 **Data Quality** 패널은 사용자에게 보이는 행사만을 대상으로
date/time/venue/fee/region/review 완성도를 보여주고, 각 결측을 해당 Review
필터로 연결한다. **누락과 오류는 분리해서 센다** — 빈 요금은 모르는 것이고,
저녁 밀롱가의 07:30은 알면서 틀린 것이라 별도 alert이 뜬다.

Review 큐는 **앞으로 열리는 행사**가 기본이며, 게시글과 어긋나는 값 → 오늘·내일
→ 시간 미확인 → 장소 미확인 → 요금 미확인 → 날짜순으로 정렬된다. 모든 조치에
Save & Next가 붙어 있어 여덟 건을 검토하는 데 목록으로 여덟 번 돌아가지 않는다.

Sources 페이지의 **Decision** 열은 사람이 내린 판단(ACTIVE / KEEP / REPLACE /
DISABLE / MONITOR)을 이유·날짜와 함께 기록한다. 옆에 권고가 근거 숫자와 함께
표시되지만 **자동으로 적용되지 않는다**. REPLACE를 기록해도 수집은 멈추지 않고,
중단은 별도의 조치다. 권고는 장르만 보고 지역을 보지 않으므로(부산 스윙의
대체가 서울 스윙으로 계산된다) 사람의 판단이 권고를 덮을 수 있다.

Pages: Dashboard, Intake, Review, Events, Duplicates, Sources, Venues,
Organizers, Genres & Regions, Usage, System. Unresolved Venues sits under
Venues at `/admin/venues/unresolved`.

Unresolved Venues is where a venue string becomes a venue. Each queue entry
shows the post it came from with a line of surrounding text, and offers **Link
Existing**, **New Venue** and **Not a venue** on the spot — the New Venue form
opens inline, prefilled from the string, and Create & Link registers the venue,
aliases the raw string to it and resolves the waiting events in one
transaction. Nothing is registered automatically: a misread line must not
become a permanent master record. Every decision is audited with the reviewer,
the string, the action and how many events actually moved.

The form fills itself from the string and, when the string is only a name, from
the post behind it — an address written right after the venue's own name, or on
a labelled 주소 line, never one merely present somewhere in the body. The region
follows from the address. Every field stays editable and the form says where
each value came from.

A venue can be removed. `/admin/venues` shows how many events use each one; a
venue nothing references can be deleted, and one that events point at needs
**Unlink & Delete**, whose confirmation names the count first. Unlinking sends
those events back to the raw string they were read from and puts the string
back in the queue — the posts, the evidence, the events and every review stay
where they are. **Deactivate** takes a venue out of circulation without
unlinking anything.

Every master-data screen — Genres, Regions, Venues, Organizers, Sources —
shares one **Edit** form, opened inline where the row is listed and prefilled
with what the row says. A rename keeps the row's id, so events, sources and
filters pointing at it keep pointing at it. Codes (`TANGO`, `KR-SEOUL`) and
source keys are rendered read-only: they are how everything else finds the row.
Provider credentials are never rendered and never editable. Enabling a source
through an edit clears the same validation as the Enable button. Every change
is recorded with the reviewer and the fields that differed.

The pipeline runs as five scheduler jobs: `source-intake` discovers posts
through a provider's search API, `content-acquisition` fetches the original
post behind each result, `engine-ingest` hands new items to the Information
Engine, `engine-reprocess` re-extracts items whose body arrived later — or whose stored
extraction came from an older ENGINE_VERSION (v0.96.3) — and
`event-normalization` builds the searchable event rows and then resolves
duplicates — one job so that order is guaranteed.

When the *extractor* changes rather than the content, the bodies already stored
hold candidates an older engine produced. `source_item_content.extracted_engine_version`
records which version last read each body, so the `engine-reprocess` job walks exactly
those rows — 25 per tick, the DB row itself acting as the cursor, so a restart resumes
instead of re-reading the first batch. That scheduler pass is the operational path.
`GET /api/admin/events/reextract-backlog` reports what is left
(current/outdated/stalled). `POST /api/admin/events/reextract` runs one batch by hand
for diagnosis: by default the same engine-version-aware queue, and `force=true` to
re-read everything regardless, paged with the `after_item_id` cursor the response
returns. Candidates a person has acted on are skipped on every path.

An operator registers a source, presses **Test**, then **Enable**. The
scheduler collects only from enabled sources whose interval has elapsed
(minimum 10 minutes), stores the raw items deduplicated by content hash, and
hands them to the Information Engine. Live collection needs the platform's API
credentials in `.env`; without them a source can still be tested and collected
against the engine's recorded snapshots.

## Repository Structure

```
DanceMate/
├─ engine/            Information Engine v0.74 (src, tests, config, data)
├─ runtime/           DanceMate Runtime: API, config, migrations, health, adapters
├─ scheduler/         periodic worker and job registry
├─ collector/         Dance Event Source intake (v0.75)
├─ admin/             Human Verification Console (v0.76)
├─ migrations/runtime/ numbered PostgreSQL migrations
├─ scripts/           install / start / stop / check / backup / restore
├─ deploy/rockpro64/  ROCKPro64 architecture, policy and deployment procedure
├─ tests/             product runtime test suite
├─ data/ logs/ backup/ runtime data (git-ignored, .gitkeep only)
├─ Dockerfile         ARM64-capable runtime image
├─ docker-compose.yml postgres + runtime + scheduler
├─ .env.example       environment template (no secrets)
└─ VERSION            product runtime version
```

## Development

```bash
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

pytest                       # product runtime tests (133)
cd engine && pytest          # Information Engine regression (559)
```

## Staging (ROCKPro64 target)

The board reuses its existing PostgreSQL, so it selects a different compose
file through `.env` (`DANCEMATE_COMPOSE_FILE`). See
`deploy/rockpro64/README.md` for the full procedure and for why every command
here goes through a script rather than a bare `docker compose`.

```bash
cp .env.example .env
$EDITOR .env                 # set POSTGRES_PASSWORD: openssl rand -base64 24
                              # and, on the board, DANCEMATE_COMPOSE_FILE=
                              # deploy/rockpro64/docker-compose.external-postgres.yml

scripts/install-rockpro64.sh # host readiness check (--prepare to create dirs)
scripts/start-server.sh      # builds if needed, then starts (postgres +) runtime + scheduler
scripts/check-server.sh      # exit 0 all PASS, 1 a component FAILed, 2 unreachable
scripts/stop-server.sh       # stop; never removes volumes
```

To deploy a **new version** on the board later (build a new image, back up
first, recreate, health-gate), use `scripts/deploy-production.sh` instead -
see `deploy/rockpro64/README.md`.

Health output:

```
DanceMate Server
Runtime ........ PASS
Database ....... PASS
Scheduler ...... PASS
Information .... PASS
Storage ........ PASS
Backup ......... PASS
```

## Backup and Restore

```bash
scripts/backup.sh                              # timestamped backup, retention 7
scripts/restore.sh --list
scripts/restore.sh dancemate-backup-YYYYmmdd-HHMMSS         # dry run, changes nothing
scripts/restore.sh dancemate-backup-YYYYmmdd-HHMMSS --yes   # apply
```

A backup contains `postgres.dump` (pg_dump custom format), `engine.sqlite3`
(taken with SQLite's online backup API, safe against a live engine connection)
and `manifest.json`. Restore stops the scheduler, takes a pre-restore safety
copy, then applies the named backup.

## Data persistence

| Path                          | Container                  | Survives                       |
|-------------------------------|----------------------------|--------------------------------|
| `dancemate-postgres-data`     | `/var/lib/postgresql/data` | restart, recreation, reboot    |
| `$ENGINE_DATA_DIR`            | `/app/engine/data`         | restart, recreation, reboot    |
| `$DANCEMATE_DATA_DIR`         | `/var/lib/dancemate`       | restart, recreation, reboot    |
| `$DANCEMATE_LOG_DIR`          | `/var/log/dancemate`       | restart, recreation, reboot    |
| `$DANCEMATE_BACKUP_DIR`       | `/var/backups/dancemate`   | restart, recreation, reboot    |

`stop-server.sh` never passes `-v` to `docker compose down`, so stopping the
stack never removes any of them.

## Network policy

**LAN firewall required. No WAN port forwarding.** The runtime API is an
unauthenticated staging admin surface. PostgreSQL is never published to the
host. Set `DANCEMATE_BIND_ADDRESS` to the board's LAN address in production
staging.

## Credential handling in shared artifacts

Before sharing a session transcript, log, or packaged output outside this
machine, secrets must be scrubbed **by key identity, not by value shape**.
Matching on value length or content (e.g. "long strings look like secrets")
produces false positives on perfectly ordinary settings - `POSTGRES_DB` is
just the word `dancemate` - and rewrites harmless values across paths, image
names, and docs instead of the credential that mattered.

Match on the `.env` key name instead. A key is sensitive when it ends in one
of:

```
PASSWORD, SECRET, TOKEN, API_KEY, _KEY
```

(e.g. `NAVER_CLIENT_SECRET`, `KAKAO_REST_API_KEY`, `POSTGRES_PASSWORD`).
Never include the actual value of a matched key in anything meant to leave
this machine - redact it (`NAVER_CLIENT_SECRET=<redacted>`), don't paraphrase
or truncate it.
