#!/usr/bin/env bash
set -euo pipefail

# DanceMate - ROCKPro64 installation script
#
# Target: PINE64 ROCKPro64 v2.1 / RK3399 / ARM64 / Armbian 26.8.3 (Debian 13 Trixie)
#
# v0.74에서 다음을 수행할 예정이다.
#   - 필수 패키지 및 docker / docker compose 확인
#   - /var/lib/dancemate, /var/log/dancemate, /var/backups/dancemate 준비
#   - .env 생성 안내 (.env.example 기반)
#   - systemd unit 등록 (host reboot 후 자동 시작)
#   - SD card write 최소화 설정
#
# 현재 단계에서는 runtime이 존재하지 않으므로 어떠한 설치/삭제도 수행하지 않는다.

echo "DanceMate v0.74 runtime is not installed yet."
exit 0
