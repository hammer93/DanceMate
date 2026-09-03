# DanceMate Information Engine PoC v0.73
## Remediation Recommendation Runtime Outcome + Selection Effectiveness

v0.73은 v0.72의 Shadow Remediation Recommendation과 Human Architecture Selection을
실제 Family Recovery Generation 결과와 연결한다.

핵심 원칙:

> 추천한 수정안과 사람이 선택한 수정안을 기록하는 데서 끝내지 않는다.
> 실제 Re-Arm 이후 Stabilized Generation이 장기 성공했는지, 다시 재발했는지를 연결해
> Recommendation의 적중률과 Human Override의 결과를 다시 학습한다.

## Outcome Lifecycle

Family Recovery가 STABLE이 되어 Generation Outcome이 생성되면:

```text
STABILIZED_PENDING
```

Recommendation Outcome도 함께 등록한다.

Generation이 이후:

```text
SUSTAINED_SUCCESS
RECURRENCE_FAILED
```

중 하나가 되면 Recommendation Outcome을 최종 판정한다.

## Outcome Classes

```text
RECOMMENDATION_HELPFUL
RECOMMENDATION_HARMFUL
HUMAN_OVERRIDE_SUCCESS
HUMAN_OVERRIDE_FAILURE
MANUAL_SELECTION_SUCCESS
MANUAL_SELECTION_FAILURE
```

추천안과 Human SELECT가 같고 Generation이 SUSTAINED_SUCCESS면
`RECOMMENDATION_HELPFUL`.

추천안과 선택이 같지만 RECURRENCE_FAILED면
`RECOMMENDATION_HARMFUL`.

추천과 다른 Historical Remediation을 Human이 선택했다면
성공/실패에 따라 `HUMAN_OVERRIDE_SUCCESS/FAILURE`로 남긴다.

## Selection Regret

선택한 경로가 실패했을 때:

```text
max(0, recommended_score - selected_score)
```

를 `selection_regret_score`로 기록한다.

성공한 선택은 Regret 0이다.

이 값은 실제 Counterfactual 성공을 가정하지 않고,
당시 Ranking 기준에서 더 높은 점수의 추천을 거부했을 때 발생한
보수적 Selection Regret 신호로만 사용한다.

## Recommendation Effectiveness Profile

Family Signature별로 다음을 집계한다.

- Recommendation Count
- Human Selection Count
- Acceptance Count
- Override Count
- Resolved Count
- Recommendation Helpful / Harmful
- Override Success / Failure
- Acceptance Rate
- Recommendation Helpful Rate
- Override Success Rate
- Average Selection Regret
- Calibration Band

Calibration:

```text
Resolved < 3                        → LOW_DATA
Helpful >= 2 / Harmful 0 / Regret<=.05 → WELL_CALIBRATED
Harmful >= 2 or AvgRegret >= .10   → MISALIGNED
그 외                              → LEARNING
```

## Safety

- STABLE Generation 등록 전에는 Runtime Outcome 확정 금지
- SUSTAINED_SUCCESS / RECURRENCE_FAILED 전에는 PENDING
- Recommendation Outcome이 자동으로 Production Policy를 변경하지 않음
- Human Override 성공을 Recommendation 성공으로 계산하지 않음
- Recommendation 실패와 Human Override 실패를 분리
- Selection Regret은 Counterfactual 사실로 취급하지 않음
- v0.72 Shadow-only Recommendation 유지
- v0.71 Family Generation Runtime Memory 유지
- 광고/스폰서/수익 신호 사용 안 함

## New DB Tables

- `origin_threshold_recommendation_fallback_family_recommendation_outcomes`
- `origin_threshold_recommendation_fallback_family_recommendation_effectiveness_profiles`
- `origin_threshold_recommendation_fallback_family_recommendation_outcome_events`

## New CLI

```powershell
python -m src.main recommendation-fallback-family-recommendation-outcomes
python -m src.main recommendation-fallback-family-recommendation-effectiveness
python -m src.main recommendation-fallback-family-recommendation-outcome-events
python -m src.main recommendation-fallback-family-recommendation-outcome-status
```

## Daily Operations

추가 섹션:

### Recommendation Runtime Outcome / Selection Effectiveness

표시:

- Recommended Remediation
- Selected Remediation
- Recommendation Accepted
- Human Override
- Generation Status
- Outcome Class
- Selection Regret
- Acceptance Rate
- Recommendation Helpful Rate
- Override Success Rate
- Calibration Band

## Verification

현재 테스트 컬렉션:

```text
559 tests collected
```

v0.73 신규:

```text
15 passed
```

추가 변경 영향:

```text
Family Generation Memory 15 passed
Family Remediation Ranking 16 passed
```

Synthetic Integration:

```text
SHADOW_PREFERRED GOOD-73
→ Human SELECT GOOD-73
→ Stabilized Generation
→ Recommendation Outcome STABILIZED_PENDING
→ Generation SUSTAINED_SUCCESS
→ RECOMMENDATION_HELPFUL
→ Acceptance=true
→ Recommendation Helpful Rate=1.0
```

PASS.

## 다음 단계

v0.74는 `Recommendation Calibration Guard + Adaptive Shadow Weighting`이 적절하다.

v0.73에서 Recommendation이 실제로 맞았는지 학습할 수 있으므로,
다음에는 Family별 Calibration 상태를 Ranking에 피드백해야 한다.

권장 방향:

```text
Recommendation Outcome Memory
→ Calibration Profile
→ WELL_CALIBRATED / LEARNING / MISALIGNED
→ Shadow Weight Adjustment
→ Misaligned Family Recommendation Dampening
→ Human Review Required
```

단 Production 자동 변경은 계속 금지한다.

즉 v0.74의 목표는:

> “추천 결과를 측정한다”에서
> “추천이 반복해서 틀리는 Family에서는 스스로 영향력을 낮춘다.”

로 가는 것이다.
