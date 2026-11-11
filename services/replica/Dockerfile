FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY packages/manga_common /app/packages/manga_common
COPY services/replica /app/services/replica

RUN pip install --upgrade pip && \
    pip install /app/packages/manga_common && \
    pip install -r /app/services/replica/requirements.txt

RUN mkdir -p /opt/mangapoisk-reborn/data/replica && \
    chown -R app:app /opt/mangapoisk-reborn/data
USER app
WORKDIR /app/services/replica

EXPOSE 8108
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8108/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8108"]
