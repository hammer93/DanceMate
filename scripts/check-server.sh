#!/usr/bin/env bash
set -euo pipefail

# DanceMate - server health check
#
# v0.74 이후 이 script는 아래 형태의 상태를 출력하는 것을 목표로 한다.
#
#   DanceMate Server
#   Runtime ........ PASS
#   Database ....... PASS
#   Scheduler ...... PASS
#   Information .... PASS
#   Storage ........ PASS
#   Backup ......... PASS
#
# 각 항목의 판정 기준(예정):
#   Runtime      - API health endpoint 응답
#   Database     - PostgreSQL 연결 및 schema version 확인
#   Scheduler    - periodic worker heartbeat
#   Information  - Information Engine 처리 상태
#   Storage      - data 디렉토리 쓰기 가능 여부 및 여유 용량
#   Backup       - 최근 backup 존재 여부 및 생성 시각
#
# 실제로 확인하지 않은 항목을 PASS로 출력하지 않는다.
# 현재 단계에서는 확인할 runtime이 존재하지 않는다.

echo "DanceMate v0.74 runtime is not installed yet."
exit 0
