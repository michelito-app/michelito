# syntax=docker/dockerfile:1
# Imagen de la demo pública (Michelito): solo `finanzas demo`, datos inventados, sin Gmail ni
# keyring. Ver docs/despliegue.md. Las imágenes base van fijadas por digest (Dependabot las sube).

# 1. La interfaz: compila frontend/ a src/finanzas/web/static/ (como `npm run build`).
FROM node:26-slim@sha256:e6bedef217677b276c591795e169840edd9096dbf13f29df8ef8d1856b8820bc AS interfaz
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# 2. La app: un entorno con uv, sin dependencias de desarrollo y sin instalar en modo editable
#    (el paquete, con la interfaz compilada, queda dentro de .venv).
FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928 AS app
COPY --from=ghcr.io/astral-sh/uv:0.13.8@sha256:5cc1805e2426484abca4ad46ea783bab281fdb225fd82d8ce6d66a81254bac85 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src/ src/
COPY --from=interfaz /src/src/finanzas/web/static/ src/finanzas/web/static/
# Los documentos de descubrimiento de googleapiclient (≈ 100 MB) solo los usa el sync de Gmail,
# que en la demo no existe.
RUN uv sync --frozen --no-dev --no-editable \
    && test -f /app/.venv/lib/python3.13/site-packages/finanzas/web/static/index.html \
    && rm -rf /app/.venv/lib/python3.13/site-packages/googleapiclient/discovery_cache/documents

# 3. La imagen final: el mismo Python, el entorno y nada más (ni uv, ni Node, ni el código fuente).
FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928
LABEL org.opencontainers.image.title="Michelito (demo)" \
      org.opencontainers.image.description="Demo pública de finanzas con datos inventados" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later"
# Sin pip: en la imagen no se instala nada.
RUN rm -rf /usr/local/bin/pip* /usr/local/lib/python3.13/site-packages/pip* \
    && groupadd --system --gid 10001 michelito \
    && useradd --system --uid 10001 --gid michelito --no-create-home \
       --home-dir /nonexistent --shell /usr/sbin/nologin michelito \
    && install -d -o michelito -g michelito -m 700 /datos
COPY --from=app /app/.venv /app/.venv
# FINANZAS_MODO=demo: en el contenedor solo existen `demo` y `opiniones`. Las demás opciones de
# la demo (host público, proxy confiable, repo) las pone docker-compose.yml.
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FINANZAS_MODO=demo \
    FINANZAS_DEMO_DIR=/datos \
    FINANZAS_DEMO_ESCUCHAR=0.0.0.0 \
    FINANZAS_DEMO_PUERTO=8600
USER michelito
WORKDIR /datos
VOLUME /datos
EXPOSE 8600
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ['FINANZAS_DEMO_PUERTO'] + '/api/health', timeout=4)"]
ENTRYPOINT ["finanzas", "demo"]
