# syntax=docker/dockerfile:1
# Image of the public demo (Michelito): `michelito demo`, made-up data, no Gmail and no keyring.
# The same image runs the hosted app (`michelito hosted`, with MICHELITO_MODE=hosted: only the
# server commands) when deploy/docker-compose.yml says so. See docs/deployment.md. Base images are pinned by digest (Dependabot bumps them).

# 1. The interface: builds frontend/ into src/michelito/web/static/ (like `npm run build`).
FROM node:25-slim@sha256:81db02c4b671288a03915da9534dbd54f96d0e7c24d80ccc54f5b36b2e684370 AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# 2. The app: an environment built with uv, without dev dependencies and not installed in
#    editable mode (the package, with the built interface, ends up inside .venv).
FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90 AS app
COPY --from=ghcr.io/astral-sh/uv:0.13.8@sha256:5cc1805e2426484abca4ad46ea783bab281fdb225fd82d8ce6d66a81254bac85 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src/ src/
COPY --from=frontend /src/src/michelito/web/static/ src/michelito/web/static/
# googleapiclient's discovery documents (≈ 100 MB) are dropped except Gmail's, which the hosted
# Gmail sync builds its client from (`gmail.build_client`); without it the read fails with
# UnknownApiNameOrVersion.
ARG DISCOVERY=/app/.venv/lib/python3.13/site-packages/googleapiclient/discovery_cache/documents
RUN uv sync --frozen --no-dev --no-editable \
    && test -f /app/.venv/lib/python3.13/site-packages/michelito/web/static/index.html \
    && find "$DISCOVERY" -type f ! -name gmail.v1.json -delete \
    && test -f "$DISCOVERY/gmail.v1.json"

# 3. The final image: the same Python, the environment and nothing else (no uv, Node or sources).
FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
LABEL org.opencontainers.image.title="Michelito (demo)" \
      org.opencontainers.image.description="Public demo of a personal finance tool, with made-up data" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later"
# No pip: nothing gets installed in the image.
RUN rm -rf /usr/local/bin/pip* /usr/local/lib/python3.13/site-packages/pip* \
    && groupadd --system --gid 10001 michelito \
    && useradd --system --uid 10001 --gid michelito --no-create-home \
       --home-dir /nonexistent --shell /usr/sbin/nologin michelito \
    && install -d -o michelito -g michelito -m 700 /data \
    && install -d -o michelito -g michelito -m 700 /run/michelito-pdf
COPY --from=app /app/.venv /app/.venv
# MICHELITO_MODE=demo: only `demo` and `feedback` exist in the container. The other demo options
# (public host, trusted proxy, repo) are set by docker-compose.yml.
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MICHELITO_MODE=demo \
    MICHELITO_DEMO_DIR=/data \
    MICHELITO_DEMO_LISTEN=0.0.0.0 \
    MICHELITO_DEMO_PORT=8600
USER michelito
WORKDIR /data
VOLUME /data
EXPOSE 8600
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ['MICHELITO_DEMO_PORT'] + '/api/health', timeout=4)"]
ENTRYPOINT ["michelito", "demo"]
