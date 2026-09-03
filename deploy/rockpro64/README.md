# DanceMate - ROCKPro64 Deployment

## Target

- PINE64 ROCKPro64 v2.1
- RK3399
- ARM64 / aarch64
- RAM 4GB
- microSD 32GB
- Armbian 26.8.3
- Debian 13 Trixie
- Kernel 6.18.x

## Deployment Policy

- LAN only
- No public Internet exposure
- Automatic recovery after host reboot
- SD card write minimization
- Persistent data
- Backup required
- Health check required

## v0.74 Acceptance

1. Host boot
2. DanceMate auto-start
3. PostgreSQL connection
4. Information Engine start
5. API Health
6. Scheduler
7. Test data processing
8. Recommendation Memory persistence
9. Host reboot
10. Memory restored
11. Runtime Outcome preserved
12. Processing continues

## 현재 상태

이번 단계(v0.73 Repository Baseline)에서는 ROCKPro64 deployment를 수행하지 않는다.
실제 configuration(Docker / Environment / System 설정)은 v0.74에서 이 디렉토리에 추가된다.
