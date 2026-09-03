# DanceMate v0.74 runtime Dockerfile
# Runtime implementation will be added in v0.74.
# Target architecture: linux/arm64
#
# 이번 단계(v0.73 Repository Baseline)에서는 runtime이 아직 존재하지 않으므로
# 동작하지 않는 임의의 build stage를 만들지 않는다.
#
# v0.74에서 다음이 추가될 예정이다.
#   - base image (python slim / arm64)
#   - engine + runtime source COPY
#   - dependency install
#   - non-root runtime user
#   - healthcheck
#   - entrypoint
