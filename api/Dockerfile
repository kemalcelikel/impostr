FROM python:3.12.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY api/requirements.lock ./requirements.lock
RUN python -m pip install --no-cache-dir --require-hashes -r requirements.lock \
    && groupadd --system --gid 10001 impostr \
    && useradd --system --uid 10001 --gid impostr --no-create-home --shell /usr/sbin/nologin impostr

COPY api/alembic.ini ./alembic.ini
COPY api/app ./app
COPY api/migrations ./migrations
COPY overnight-agent/PROJECT.md.example overnight-agent/AGENTS.md.example overnight-agent/BACKLOG.md.example ./templates/overnight-agent/

USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header", "--proxy-headers", "--forwarded-allow-ips=*"]

FROM runtime AS development

USER root
COPY api/requirements-dev.lock ./requirements-dev.lock
RUN python -m pip install --no-cache-dir --require-hashes -r requirements-dev.lock

COPY api/pyproject.toml ./pyproject.toml
COPY api/tests ./tests
# Keep the root helper outside /app so API lint only covers API sources.
COPY scripts/backlog.py /opt/impostr-compat/backlog.py
COPY scripts/imp017_fixtures.py /opt/impostr-pdf-fixtures/imp017_fixtures.py
USER 10001:10001
CMD ["pytest", "-p", "no:cacheprovider"]
