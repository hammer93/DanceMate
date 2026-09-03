# DanceMate Daily Operations Summary — 2026-08-28

- Daily Run ID: `de011074-0003-458d-8f04-96e1009fc2e0`
- Health: **YELLOW**
- P0: **0**
- Human Review: **2** (High 1)

## Event Confidence
- HIGH_CONFIDENCE: 1

## Field Confidence
- VERIFIED: 4

## Source Operations
| Source | Authority | Access | Yield | Access Failure | Recovery |
|---|---|---|---:|---:|---:|
| SRC-D-001 | SECONDARY | UNKNOWN | N/A | N/A | N/A |
| SRC-D-002 | SECONDARY | UNKNOWN | N/A | N/A | N/A |
| SRC-F-001 | PRIMARY_VENUE | ACCESS_LIMITED | N/A | N/A | N/A |
| SRC-F-002 | PRIMARY_ORGANIZER | ACCESS_LIMITED | N/A | N/A | N/A |
| SRC-N-001 | AGGREGATOR | LOGIN_REQUIRED | 50.0% | 66.7% | 0.0% |
| SRC-N-002 | SECONDARY | UNKNOWN | 50.0% | 0.0% | 100.0% |

## Recovery Status
- PENDING: 1
- RESOLVED: 1

## Human Review Queue
1. [NORMAL] EVENT_REVIEW — EVENT_HIGH_CONFIDENCE
2. [HIGH] RECOVERY_REVIEW — BODY_UNAVAILABLE

## P0
- P0 없음

## Human-in-the-loop Metrics
- Review Count: 1
- Manual Correction Rate: 100.0%
- Machine↔Human Disagreement: 100.0%
- Approval Rate: 0.0%
- Rejection Rate: 0.0%
- Hold Rate: 0.0%
- Evidence-backed Resolution: 100.0%
- Avg Review Turnaround: 0.69 sec
- Reviewer Reliability: PROXY_ONLY

## Correction Hotspots
| Priority | Source | Field | Reviews | Corrections | Holds | Score |
|---|---|---|---:|---:|---:|---:|
| P2 | SRC-N-001 | fee | 1 | 1 | 0 | 4 |
| P2 | SRC-N-002 | fee | 1 | 1 | 0 | 4 |

## Improvement Backlog
1. [P2/LOW] SRC-N-001 × fee — SRC-N-001의 fee에서 Human Review 수정/기각이 1건 발생
   - EVIDENCE/FEE: Fee occurrence-level verification 강화
   - COLLECTOR/NAVER_BLOG: Naver Blog 추출 안정화
2. [P2/LOW] SRC-N-002 × fee — SRC-N-002의 fee에서 Human Review 수정/기각이 1건 발생
   - EVIDENCE/FEE: Fee occurrence-level verification 강화
   - COLLECTOR/NAVER_CAFE: Naver Cafe 본문/게시판 수집 규칙 정밀화

## Change Effect Verdicts
- 아직 Change verdict 없음

## Adaptive Shadow Verdicts
- 아직 Adaptive Shadow verdict 없음

## Shadow Safety Gate
- Status: **OBSERVING**
- Samples: 0 / 20
- Agreement: N/A
- Critical False IMPROVED: 0
- Unsafe IMPROVED: 0
- Reason: Shadow samples 0 < minimum 20

## Rolling Shadow Stability
- Status: **OBSERVING**
- Total Samples: 0
- Downgrade Detected: NO
- Window 7: OBSERVING (samples=0, agreement=N/A, unsafe=0)
- Window 14: OBSERVING (samples=0, agreement=N/A, unsafe=0)
- Window 30: OBSERVING (samples=0, agreement=N/A, unsafe=0)
- Reason: Cumulative Safety status is OBSERVING

## Adaptive Promotion Candidates
- 없음

## Adaptive Promotion Leases
- 없음

## Promotion Human Reviews
- 없음

## Operator Decision
- GREEN: 자동 운영 지속
- YELLOW: Human Review Queue 우선 확인
- RED: P0 해결 전 VERIFIED 결과 외부 노출 금지