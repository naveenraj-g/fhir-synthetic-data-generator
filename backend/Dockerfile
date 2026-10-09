FROM python:3.12-slim AS builder

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml ./
RUN uv venv && uv sync --no-dev

COPY . .

FROM python:3.12-slim

# Synthea runs *inside* this image (SYNTHEA_MODE=local): a container cannot start sibling containers without the host's
# Docker socket, so deployment bundles a JRE and the pinned Synthea jar instead. For development on a machine with
# Docker, leave the default (SYNTHEA_MODE=docker, see docker/synthea/Dockerfile) and run the API on the host.
ARG SYNTHEA_VERSION=v4.0.0
RUN apt-get update \
    && apt-get install -y --no-install-recommends default-jre-headless curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /app/vendor/synthea \
    && curl -fsSL -o /app/vendor/synthea/synthea-with-dependencies.jar \
       "https://github.com/synthetichealth/synthea/releases/download/${SYNTHEA_VERSION}/synthea-with-dependencies.jar" \
    && apt-get purge -y curl && apt-get autoremove -y

WORKDIR /app
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH" \
    SYNTHEA_MODE=local

EXPOSE 8000
# Create/upgrade the job table, then serve.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
