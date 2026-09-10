# THE HOUSE — real container deployment (Railway primary, Render fallback).
#
# Stateful FastAPI service on Base:
#   * memory.db IS the business -> mounted on a PERSISTENT VOLUME at /data
#   * ACP money-out uses the Node CLI -> installed, but SAFE-BY-DEFAULT OFF.
#     The public deploy only RECEIVES (CDP x402); it never sends unless
#     HOUSE_LIVE_MONEY_OUT=1 (you keep that OFF on the public deploy).
#
# Build locally:  docker build -t the-house .
# Run locally:    docker run --rm -p 8000:8000 -v the-house-data:/data the-house

FROM python:3.12-slim-bookworm

# Node 22 (the @virtuals-protocol/acp-cli is a Node CLI; matches tested version)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1) Python deps — resolved from pyproject.toml (single source of truth).
#    NOT requirements.lock.txt: that freeze is not self-consistent
#    (eth-account 0.14 vs signinwithethereum's <0.14) and re-install fails.
#    The loose pins in pyproject are exactly what built the working venv.
COPY pyproject.toml ./
RUN python -c "import tomllib,sys; print('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > /deps.txt \
    && pip install --no-cache-dir -r /deps.txt \
    && rm -f /deps.txt

# 2) ACP CLI (optional money-out path). Non-fatal: if the registry is
#    unreachable the image still builds and ACP degrades gracefully at runtime.
RUN npm install -g @virtuals-protocol/acp-cli@1.0.35 \
    || echo "acp-cli install skipped (non-fatal)"

# 3) Application code (core/ + app/ are importable packages in WORKDIR)
COPY core ./core
COPY app ./app
COPY scripts ./scripts

# 4) State + runtime env
# Build identity: .dockerignore excludes .git, so without these the pages
# render blank commit / "private build page" fallbacks. Inject at build time:
#   docker build --build-arg GIT_SHA=$(git rev-parse --short HEAD) .
# or set HOUSE_COMMIT (+ HOUSE_REPO_URL for forks) as dashboard variables
# (Railway/Render) — explicit env always wins over the build arg.
ARG GIT_SHA=""
ENV HOUSE_MEMORY_DB=/data/memory.db \
    HOUSE_PORT=8000 \
    PORT=8000 \
    HOUSE_COMMIT=${GIT_SHA} \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

# Honors $PORT (PaaS convention), falls back to $HOUSE_PORT, then 8000.
CMD ["sh", "-c", "exec python -m uvicorn app.x402.seller:app --host 0.0.0.0 --port ${PORT:-${HOUSE_PORT:-8000}}"]
