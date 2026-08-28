FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Dependencies first, so a code change does not reinstall the world.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY bot ./bot
COPY admin ./admin
COPY tools ./tools
RUN uv sync --frozen --no-dev

# The volume is created by Docker as root; give the unprivileged user a home
# and let compose mount /data with the right ownership.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /app /data
USER appuser

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/data/numbers.sqlite3

CMD ["python", "-m", "bot"]
