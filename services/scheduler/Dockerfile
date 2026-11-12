FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY packages/manga_common /app/packages/manga_common
COPY services/scheduler /app/services/scheduler
# The scheduler reuses the source adapters in-process for the resumable
# catalogue crawl; no parser HTTP endpoint is needed for pagination.
COPY services/parser/app/adapters /app/services/parser/app/adapters

RUN pip install --upgrade pip && \
    pip install /app/packages/manga_common && \
    pip install -r /app/services/scheduler/requirements.txt

USER app
WORKDIR /app/services/scheduler

CMD ["python", "-m", "app.main"]
