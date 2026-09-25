FROM python:3.12.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.lock ./requirements.lock
RUN python -m pip install --no-cache-dir --require-hashes -r requirements.lock \
    && groupadd --system --gid 10001 impostr \
    && useradd --system --uid 10001 --gid impostr --no-create-home --shell /usr/sbin/nologin impostr

COPY alembic.ini ./alembic.ini
COPY app ./app
COPY migrations ./migrations

USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]

FROM runtime AS development

USER root
COPY requirements-dev.lock ./requirements-dev.lock
RUN python -m pip install --no-cache-dir --require-hashes -r requirements-dev.lock

COPY pyproject.toml ./pyproject.toml
COPY tests ./tests
USER 10001:10001
CMD ["pytest", "-p", "no:cacheprovider"]
