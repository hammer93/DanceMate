# DanceMate v0.74 runtime image.
#
# Target architecture: linux/arm64 (PINE64 ROCKPro64 / Rockchip RK3399,
# Armbian 26.8.3 / Debian 13 Trixie). Built and run for linux/amd64 during
# development; nothing below is architecture specific.
#
# Python 3.12: the Information Engine v0.73 is standard library only but uses
# PEP 604 (`str | None`) annotations at runtime, so it needs >= 3.10. 3.12-slim
# is the newest official multi-arch tag with aarch64 wheels for every runtime
# dependency (pydantic-core, psycopg-binary), which keeps the image free of a
# compiler toolchain.
#
# One image serves both the runtime API and the scheduler worker; the compose
# service picks the process. Two containers, one build, minimal RAM on a 4GB host.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first so source edits do not invalidate the wheel layer.
COPY runtime/requirements.txt /app/runtime/requirements.txt
RUN pip install --no-cache-dir -r /app/runtime/requirements.txt

COPY runtime/ /app/runtime/
COPY scheduler/ /app/scheduler/
COPY migrations/ /app/migrations/
COPY engine/ /app/engine/
COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
# Deployment acceptance tool: it plants and verifies the persistence markers
# from inside the container, so it has to be in the image.
COPY deploy/rockpro64/acceptance_marker.py /app/deploy/rockpro64/acceptance_marker.py
COPY VERSION /app/VERSION

# Pristine copy of the engine fixtures. A persistent volume is mounted over
# /app/engine/data, which would otherwise hide them; the entrypoint seeds any
# missing file back in without overwriting live data.
RUN mkdir -p /opt/dancemate && cp -r /app/engine/data /opt/dancemate/engine-data-seed \
 && chmod +x /usr/local/bin/docker-entrypoint.sh \
 && mkdir -p /var/lib/dancemate /var/log/dancemate /var/backups/dancemate

ENV ENGINE_ROOT=/app/engine \
    ENGINE_DATA_DIR=/app/engine/data \
    ENGINE_SEED_DIR=/opt/dancemate/engine-data-seed \
    DANCEMATE_DATA_DIR=/var/lib/dancemate \
    DANCEMATE_LOG_DIR=/var/log/dancemate \
    DANCEMATE_BACKUP_DIR=/var/backups/dancemate

# Non-root: the runtime never needs to write outside its mounted volumes.
RUN useradd --system --create-home --uid 10001 dancemate \
 && chown -R dancemate:dancemate /app /var/lib/dancemate /var/log/dancemate /var/backups/dancemate
USER dancemate

EXPOSE 8080

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "-m", "runtime"]
