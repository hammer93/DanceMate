from .correction_hotspot import analyze_correction_hotspots

FIELD_RECOMMENDATIONS={
    "fee":{
        "title":"Fee occurrence-level verification 강화",
        "actions":[
            "당일 Poster/Organizer 공지에서 fee를 우선 추출",
            "정기/과거 fee를 EXPECTED로 격리하고 당일 근거 없이는 VERIFIED 금지",
            "Poster Evidence가 있으면 fee parser 우선 실행"
        ],
        "component":"EVIDENCE/FEE"
    },
    "start_time":{
        "title":"시간 parser 및 날짜 경계 처리 개선",
        "actions":[
            "HH:MM / 오후·저녁 표현 정규화",
            "자정 이후 종료시간 end_day_offset 검증",
            "본문/포스터 시간 충돌 시 CONFLICT 생성"
        ],
        "component":"PARSER/TIME"
    },
    "venue":{
        "title":"Venue canonicalization 및 장소 근거 강화",
        "actions":[
            "별칭/한글·영문 표기 통합",
            "행사명과 장소명 혼동 방지",
            "Primary Venue source와 교차검증"
        ],
        "component":"PARSER/VENUE"
    },
    "date":{
        "title":"행사 날짜 occurrence 검증 강화",
        "actions":[
            "게시일과 행사일을 분리",
            "월/일만 있는 공지의 연도 추론 제한",
            "정기 일정은 EXPECTED, 당일 공지는 VERIFIED"
        ],
        "component":"PARSER/DATE"
    }
}

def _source_strategy(row):
    authority=row.get("authority_level")
    access=row.get("access_state")
    if authority in ("PRIMARY_ORGANIZER","PRIMARY_VENUE") and access!="OPEN":
        return {
            "title":"Primary Source access/recovery 전략 강화",
            "actions":[
                "직접 접근 실패를 정상 상태로 기록",
                "Secondary/Aggregator cross-source recovery 자동 실행",
                "동일 행사에서 Primary evidence 발견 시 즉시 승격"
            ],
            "component":"SOURCE/ACCESS"
        }
    if row.get("platform")=="NAVER_BLOG":
        return {
            "title":"Naver Blog 추출 안정화",
            "actions":[
                "본문 획득 실패/로그인 shell 탐지 강화",
                "metadata-only 결과를 VERIFIED에 사용하지 않음",
                "poster/media fallback 경로 우선"
            ],
            "component":"COLLECTOR/NAVER_BLOG"
        }
    if row.get("platform")=="NAVER_CAFE":
        return {
            "title":"Naver Cafe 본문/게시판 수집 규칙 정밀화",
            "actions":[
                "게시판별 selector 분리",
                "중복 홍보글 dedup 강화",
                "본문 vs 제목/snippet confidence 분리"
            ],
            "component":"COLLECTOR/NAVER_CAFE"
        }
    return {
        "title":"Source별 수집/파싱 규칙 점검",
        "actions":[
            "실패 유형 분류",
            "본문 품질과 Event yield 분리 측정",
            "Source별 parser regression snapshot 추가"
        ],
        "component":"SOURCE/GENERAL"
    }

def recommend_improvement_backlog(con, limit=10):
    analysis=analyze_correction_hotspots(con)
    items=[]
    rank=1

    for h in analysis["top_hotspots"][:limit]:
        field_cfg=FIELD_RECOMMENDATIONS.get(h["field"],{
            "title":f"{h['field']} field extraction 개선",
            "actions":["해당 field parser/error case 분석","Human Review 수정 사례를 regression fixture로 추가"],
            "component":f"PARSER/{h['field'].upper()}"
        })
        src_cfg=_source_strategy(h)

        priority=h["priority"]
        confidence="LOW" if h["reviews"]<3 else ("MEDIUM" if h["reviews"]<10 else "HIGH")

        item={
            "rank":rank,
            "priority":priority,
            "confidence":confidence,
            "source_id":h["source_id"],
            "source_name":h.get("source_name"),
            "field":h["field"],
            "hotspot_score":h["hotspot_score"],
            "review_count":h["reviews"],
            "correction_rate":h["correction_rate"],
            "problem_statement":(
                f"{h['source_id']}의 {h['field']}에서 Human Review 수정/기각이 "
                f"{h['modifications']+h['rejections']}건 발생"
            ),
            "recommended_epics":[
                {
                    "component":field_cfg["component"],
                    "title":field_cfg["title"],
                    "actions":field_cfg["actions"]
                },
                {
                    "component":src_cfg["component"],
                    "title":src_cfg["title"],
                    "actions":src_cfg["actions"]
                }
            ],
            "acceptance_criteria":[
                "동일 correction fixture에서 기계 결과와 Human 수정값이 일치",
                "새 regression test 추가 및 전체 pytest PASS",
                "같은 Source×Field hotspot correction rate가 후속 표본에서 감소",
                "VERIFIED 승격 시 Evidence Model/P0 규칙 우회 없음"
            ]
        }
        items.append(item)
        rank+=1

    if not items:
        items.append({
            "rank":1,
            "priority":"P3",
            "confidence":"LOW",
            "source_id":None,
            "field":None,
            "hotspot_score":0,
            "review_count":0,
            "correction_rate":None,
            "problem_statement":"아직 Human Review 표본이 부족하여 구체 Hotspot 없음",
            "recommended_epics":[
                {
                    "component":"OBSERVABILITY/REVIEW",
                    "title":"Human Review 표본 축적",
                    "actions":[
                        "실측 Review Queue 처리 지속",
                        "MODIFY/REJECT/HOLD reason과 evidence를 누락 없이 기록",
                        "Source×Field attribution 유지"
                    ]
                }
            ],
            "acceptance_criteria":[
                "Field review 누적 3건 이상",
                "Source×Field hotspot 최소 1개 계산 가능"
            ]
        })

    return {
        "backlog":items,
        "source_hotspots":analysis["source_hotspots"],
        "field_hotspots":analysis["field_hotspots"],
        "policy":{
            "priority_from_hotspot":"P1/P2/P3 그대로 사용",
            "confidence_by_sample":"LOW<3, MEDIUM<10, HIGH>=10 reviews",
            "do_not_overfit":"LOW confidence backlog는 구조 개선 후보로만 사용하고 통계적 결론으로 간주하지 않음"
        }
    }
