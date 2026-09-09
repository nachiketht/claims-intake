FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY data ./data

EXPOSE 8000

CMD ["uv", "run", "--no-dev", "--no-sync", "uvicorn", "claims.api.routes:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "src"]
