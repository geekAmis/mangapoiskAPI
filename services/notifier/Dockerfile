FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    NOTIFIER_DATABASE_URL=sqlite+aiosqlite:////data/notifier.db

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY packages/manga_common /app/packages/manga_common
COPY services/notifier /app/services/notifier

RUN pip install --upgrade pip && \
    pip install /app/packages/manga_common && \
    pip install -r /app/services/notifier/requirements.txt

RUN mkdir -p /data && chown -R app:app /data
USER app
WORKDIR /app/services/notifier

EXPOSE 8006
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8006/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8006"]
