FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
COPY pyproject.toml uv.lock README.md PLAN.md AGENTS.md ./
COPY src ./src
COPY config ./config
COPY data/Port_Tariff.pdf ./data/Port_Tariff.pdf

RUN uv sync --frozen --no-dev --no-cache

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "tariff_agent.api:app", "--host", "0.0.0.0", "--port", "8000"]
