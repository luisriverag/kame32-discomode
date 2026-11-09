# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    NUMBA_CACHE_DIR=/cache/numba XDG_CACHE_HOME=/cache \
    KAME32_MOVES_DB=/data/moves.sqlite3 KAME32_AUDIO_DIR=/audio
WORKDIR /app
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export TASK_APT_CA='-o Acquire::https::CaInfo=/run/secrets/proxy_ca'; fi; \
    apt-get ${TASK_APT_CA:-} update && \
    apt-get ${TASK_APT_CA:-} install -y --no-install-recommends ffmpeg libsndfile1 && \
    rm -rf /var/lib/apt/lists/*
COPY requirements-docker.lock ./
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir -r requirements-docker.lock
ENV OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 NUMBA_NUM_THREADS=2
RUN groupadd --gid 10001 kame && useradd --uid 10001 --gid kame --create-home kame && \
    mkdir -p /data /cache /audio && chown -R kame:kame /data /cache /audio
COPY --chown=kame:kame . .
RUN cp song_*.mp3 /audio/ && chown -R kame:kame /audio
USER kame
EXPOSE 5000 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s CMD ["python", "docker/healthcheck.py", "app"]
CMD ["gunicorn", "--bind=0.0.0.0:5000", "--workers=1", "--threads=8", "--timeout=2500", "--graceful-timeout=30", "app:app"]
