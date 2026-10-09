# syntax=docker/dockerfile:1
#
# One image with everything: the web UI (Next.js), the API (FastAPI) and Synthea (Java), started together.
#
#   docker build -t fhir-synthetic-data .
#   docker run -p 3000:3000 -v fhir-data:/app/backend/data fhir-synthetic-data
#   -> http://localhost:3000
#
# (The backend/ folder also has an API-only Dockerfile; this one is for sharing the whole application.)

# ── 1. Web UI: build Next.js into a self-contained server ──────────────────────────────────────────────────────────
FROM node:24-slim AS web
RUN npm install -g pnpm@12.4.2
WORKDIR /web
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
# The UI calls /backend/*, which Next forwards to the API. Next fixes that address at BUILD time, and inside this image
# the API is always on 127.0.0.1:8000, so it is set here and not at run time.
ENV BACKEND_URL=http://127.0.0.1:8000 \
    NEXT_OUTPUT=standalone \
    NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

# ── 2. API: Python dependencies from the lock file, then the code ──────────────────────────────────────────────────
FROM python:3.12-slim AS api
ENV UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy
RUN pip install --no-cache-dir uv
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev
COPY backend/ ./

# ── 3. Runtime ─────────────────────────────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Links the published package to the repository on GitHub and states the licence.
LABEL org.opencontainers.image.source="https://github.com/naveenraj-g/fhir-synthetic-data-generator" \
      org.opencontainers.image.description="Configurable synthetic FHIR data generator: web UI, API and Synthea in one image" \
      org.opencontainers.image.licenses="Apache-2.0"

# Synthea runs inside this image (SYNTHEA_MODE=local): a container cannot start sibling containers without the host's
# Docker socket, so a JRE and the pinned Synthea release jar are bundled. The checksum makes the build fail loudly if
# the download is ever not the release it should be.
ARG SYNTHEA_VERSION=v4.0.0
ARG SYNTHEA_SHA256=ed43c20ad40ba5c3bc724503a5af032715fe3c491620b766148e7c2361e6ecc1
RUN apt-get update \
    && apt-get install -y --no-install-recommends default-jre-headless curl ca-certificates tini bash \
    && mkdir -p /app/backend/vendor/synthea \
    && curl -fsSL -o /app/backend/vendor/synthea/synthea-with-dependencies.jar \
       "https://github.com/synthetichealth/synthea/releases/download/${SYNTHEA_VERSION}/synthea-with-dependencies.jar" \
    && echo "${SYNTHEA_SHA256}  /app/backend/vendor/synthea/synthea-with-dependencies.jar" | sha256sum -c - \
    && apt-get purge -y curl && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Node, only to run the UI server (the build tools stay in stage 1).
COPY --from=web /usr/local/bin/node /usr/local/bin/node

COPY --from=api /app/backend /app/backend
COPY --from=web /web/.next/standalone /app/web
COPY --from=web /web/.next/static /app/web/.next/static
COPY --from=web /web/public /app/web/public
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh

# Not root. Everything the app writes (the job database, generated files, caches) lives under backend/data: mount a
# volume there to keep it when the container is replaced.
RUN sed -i 's/\r$//' /usr/local/bin/entrypoint.sh \
    && chmod +x /usr/local/bin/entrypoint.sh \
    && useradd --system --create-home --uid 10001 app \
    && mkdir -p /app/backend/data \
    && chown -R app:app /app/backend/data
USER app

ENV PATH="/app/backend/.venv/bin:$PATH" \
    SYNTHEA_MODE=local \
    NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PYTHONUNBUFFERED=1

# 3000: the web UI (this is the one to publish). 8000: the API on its own (docs, scripts); publish it only if needed.
EXPOSE 3000 8000
VOLUME ["/app/backend/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3000/backend/health/ready', timeout=4)"]

ENTRYPOINT ["tini", "--", "/usr/local/bin/entrypoint.sh"]
