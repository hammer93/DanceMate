# DanceMate

DanceMate는

> "오늘 춤추고 싶은 사람이
> DanceMate를 보고 실패 없이 갈 곳을 찾는 것"

을 목표로 하는 Dance Event Information Service다.

## 현재 상태

- Information Engine: v0.73
- Runtime/Staging: 준비 단계
- Initial Server: ROCKPro64
- Initial Region: Seoul
- Initial Genres:
  - Tango
  - Salsa
  - Swing

## 현재 개발 우선순위

1. Information Engine v0.73 baseline
2. ROCKPro64 Persistent Runtime
3. Real Source Data
4. Human Verification
5. DanceMate Alpha
6. Real User Feedback

## 초기 Alpha 범위

Search
→ Event List
→ Event Detail

## Repository Structure

```
DanceMate/
├─ engine/            DanceMate Information Engine (v0.73 PoC가 이후 이 위치로 들어옴)
├─ runtime/           DanceMate Runtime / API / Admin·Status endpoint (v0.74~)
├─ collector/         Dance Event Source intake (Daum Cafe / Naver Cafe / Naver Blog / Facebook 등)
├─ scheduler/         Collector / Information Engine Job Scheduler, periodic worker
├─ admin/             Human Verification Console (v0.76~ APPROVE / EDIT / REJECT / DUPLICATE / CONFIRM)
├─ migrations/        PostgreSQL schema / Runtime DB / Version migration
├─ scripts/           ROCKPro64 설치·운영·백업·상태확인 script
├─ deploy/rockpro64/  ROCKPro64 전용 configuration 및 staging deployment 문서
├─ data/              local persistent runtime data (Git 추적 금지)
├─ logs/              runtime logs (Git 추적 금지)
├─ backup/            backup output (Git 추적 금지)
├─ docker-compose.yml v0.74 runtime composition placeholder
├─ Dockerfile         v0.74 runtime image placeholder
├─ .env.example       환경변수 템플릿 (secret 미포함)
├─ VERSION            현재 baseline 버전
└─ RELEASE_NOTES.md   릴리스 노트
```

`data/`, `logs/`, `backup/` 은 `.gitkeep` 만 추적하며 실제 운영 데이터는 Git에 올라가지 않는다.

## 현재 단계에서 아직 구현되지 않은 것

- Information Engine source import
- PostgreSQL
- Runtime API
- Scheduler implementation
- ROCKPro64 deployment
- Real Event Collectors
