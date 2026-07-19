FROM python:3.12-slim

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

ARG KAKA_REQUIREMENTS_FILE=requirements-api.txt
COPY requirements.txt requirements-api.txt /app/

RUN case "$KAKA_REQUIREMENTS_FILE" in \
        requirements-api.txt|requirements.txt) ;; \
        *) echo "unsupported KAKA_REQUIREMENTS_FILE" >&2; exit 2 ;; \
    esac \
    && python -m pip install --no-cache-dir --retries 8 --timeout 120 -r "/app/$KAKA_REQUIREMENTS_FILE"

RUN addgroup --system kaka \
    && adduser --system --ingroup kaka --home /app kaka \
    && mkdir -p /app/.kaka-local/storage /app/.kaka-local/object-storage \
    && chown -R kaka:kaka /app

COPY --chown=kaka:kaka . /app

USER kaka

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
    CMD ["python", "-c", "from urllib.request import urlopen; response=urlopen('http://127.0.0.1:8000/healthz', timeout=2); raise SystemExit(0 if response.status == 200 else 1)"]

CMD ["python", "-m", "uvicorn", "api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
