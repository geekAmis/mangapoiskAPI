# Build from the repository root:
#   docker build -f services/parser/Dockerfile -t mangapoisk-parser .
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN groupadd --system --gid 1001 parser \
    && useradd --system --uid 1001 --gid parser --create-home parser

WORKDIR /app/services/parser

# The shared monorepo package is installed explicitly; requirements.txt stays
# independent of relative paths so it works from the repository root and CI.
COPY packages/manga_common /app/packages/manga_common
# The shared package declares readme = "README.md"; create a build-only file if
# the repository does not provide one yet.  This does not affect runtime code.
RUN test -f /app/packages/manga_common/README.md \
    || printf '# manga-common\n' > /app/packages/manga_common/README.md

COPY services/parser/requirements.txt ./requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install /app/packages/manga_common \
    && python -m pip install -r requirements.txt

COPY --chown=parser:parser services/parser/app ./app

USER parser
EXPOSE 8001
STOPSIGNAL SIGTERM

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=3).read()"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
