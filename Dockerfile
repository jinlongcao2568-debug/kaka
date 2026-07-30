FROM python:3.12-slim AS runtime-base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src
ENV PIP_DEFAULT_TIMEOUT=120
ENV PIP_RETRIES=8
ENV KAKA_STORAGE_SCOPE=process
ENV KAKA_STORAGE_BACKEND=json-file
ENV KAKA_OBJECT_STORAGE_BACKEND=local-filesystem
ENV KAKA_QUEUE_BACKEND=storage
ENV KAKA_WORKER_RUNTIME=internal-storage-worker

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-wqy-zenhei \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-api.txt requirements.lock.txt requirements-api.lock.txt /app/

RUN addgroup --system kaka \
    && adduser --system --ingroup kaka --home /app kaka \
    && mkdir -p /app/.kaka-local/storage /app/.kaka-local/object-storage /app/.kaka-local/runtime \
    && chown -R kaka:kaka /app

COPY --chown=kaka:kaka . /app


FROM runtime-base AS api

ARG KAKA_REQUIREMENTS_FILE=requirements-api.lock.txt
RUN case "$KAKA_REQUIREMENTS_FILE" in \
        requirements-api.lock.txt|requirements.lock.txt) ;; \
        *) echo "unsupported KAKA_REQUIREMENTS_FILE" >&2; exit 2 ;; \
    esac \
    && python -m pip install --no-cache-dir --retries 8 --timeout 120 --require-hashes -r "/app/$KAKA_REQUIREMENTS_FILE"

USER kaka

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
    CMD ["python", "-c", "from urllib.request import urlopen; response=urlopen('http://127.0.0.1:8000/healthz', timeout=2); raise SystemExit(0 if response.status == 200 else 1)"]

CMD ["python", "-m", "uvicorn", "api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]


FROM runtime-base AS worker

ARG KAKA_REQUIREMENTS_FILE=requirements.lock.txt
RUN case "$KAKA_REQUIREMENTS_FILE" in \
        requirements-api.lock.txt|requirements.lock.txt) ;; \
        *) echo "unsupported KAKA_REQUIREMENTS_FILE" >&2; exit 2 ;; \
    esac \
    && python -m pip install --no-cache-dir --retries 8 --timeout 120 --require-hashes -r "/app/$KAKA_REQUIREMENTS_FILE"

USER kaka

CMD ["python", "-m", "runtime.controlled_gray_scheduler_worker", "--serve", "--worker-capability", "core", "--status-json", "/app/.kaka-local/runtime/controlled-gray-core-worker-status-v1.json"]


FROM worker AS browser-worker

USER root
RUN python -m playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/* /root/.cache/pip
USER kaka

CMD ["python", "-m", "runtime.operator_long_task_worker", "--serve", "--worker-capability", "browser", "--status-json", "/app/.kaka-local/runtime/operator-long-task-browser-worker-status-v1.json"]


FROM postgres:18.4-alpine3.24 AS backup-tools

RUN apk add --no-cache python3 \
    && mkdir -p /app/src/runtime /backups /source-data /restore-objects /restore-reports \
    && chown -R postgres:postgres /app /backups /source-data /restore-objects /restore-reports

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app/src

WORKDIR /app

COPY --chown=postgres:postgres src/runtime/__init__.py /app/src/runtime/__init__.py
COPY --chown=postgres:postgres src/runtime/private_pilot_backup.py /app/src/runtime/private_pilot_backup.py

USER postgres

ENTRYPOINT ["python3", "-m", "runtime.private_pilot_backup"]
CMD ["backup"]


FROM api AS default
