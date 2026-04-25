FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src:/app/tests
ENV KAKA_STORAGE_SCOPE=process
ENV KAKA_STORAGE_BACKEND=json-file
ENV KAKA_OBJECT_STORAGE_BACKEND=local-filesystem
ENV KAKA_QUEUE_BACKEND=storage
ENV KAKA_WORKER_RUNTIME=internal-storage-worker

WORKDIR /app

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir fastapi httpx pyyaml sqlalchemy uvicorn

COPY . /app

RUN mkdir -p /app/.kaka-local/storage /app/.kaka-local/object-storage

EXPOSE 8000

CMD ["python", "-c", "from api.main import create_app; create_app(); print('kaka local runtime bootstrap ready')"]
