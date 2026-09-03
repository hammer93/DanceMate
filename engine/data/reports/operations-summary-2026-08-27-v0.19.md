# DanceMate Daily Operations Summary — 2026-08-27

- Daily Run ID: `AD-HOC`
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
| SRC-N-001 | AGGREGATOR | LOGIN_REQUIRED | 100.0% | 50.0% | 0.0% |
| SRC-N-002 | SECONDARY | OPEN | 100.0% | 0.0% | 100.0% |

## Recovery Status
- PENDING: 1
- RESOLVED: 1

## Human Review Queue
1. [NORMAL] EVENT_REVIEW — EVENT_HIGH_CONFIDENCE
2. [HIGH] RECOVERY_REVIEW — BODY_UNAVAILABLE

## P0
- P0 없음

## Operator Decision
- GREEN: 자동 운영 지속
- YELLOW: Human Review Queue 우선 확인
- RED: P0 해결 전 VERIFIED 결과 외부 노출 금지