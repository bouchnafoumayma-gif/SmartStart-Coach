FROM python:3.12-slim-bookworm AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Create non-root user for runtime
RUN addgroup --system app && adduser --system --ingroup app app

# -----------------------------
# Builder stage
# -----------------------------
FROM base AS builder

COPY --from=ghcr.io/astral-sh/uv:0.10.0 /uv /bin/uv

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first (cached layer)
COPY pyproject.toml ./
COPY uv.loc[k] ./
RUN uv sync --no-dev --no-install-project --compile-bytecode

# Copy source and install project
COPY src/ ./src/
RUN uv sync --no-dev --compile-bytecode

# -----------------------------
# Runtime stage
# -----------------------------
FROM base AS final

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/.venv /app/.venv
COPY aegra.json .
COPY src/ ./src/

# Aegra (0.10.7) charge le graphe sous le nom "aegra_graphs.<id>" sans creer le paquet
# parent "aegra_graphs" : les imports relatifs du graphe (from .analyse import ...) echouent.
# On declare ce paquet a chaque demarrage de Python avec un fichier .pth (actif aussi dans
# le sous-processus uvicorn lance par "aegra serve"). Les deux dossiers couvrent les modules
# places directement dans src/ ou dans src/coach/ (un dossier absent est ignore).
RUN printf "import sys, types; m = types.ModuleType('aegra_graphs'); m.__path__ = ['/app/src', '/app/src/coach']; sys.modules['aegra_graphs'] = m\n" \
    > /app/.venv/lib/python3.12/site-packages/aegra_graphs.pth

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"

EXPOSE 2026

USER app

CMD ["aegra", "serve"]