# Build: instala as dependencias (sem dev) e o pacote num virtualenv isolado
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Camada de dependencias separada do codigo para aproveitar cache
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable


# Runtime: so o virtualenv + arquivos do Alembic, usuario sem privilegios
FROM python:3.12-slim

RUN useradd --system --uid 10001 --no-create-home app

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY alembic.ini ./
COPY alembic ./alembic

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

USER 10001

EXPOSE 8000

# Um unico worker: multiplas instancias duplicariam a coleta de eventos
CMD ["uvicorn", "my_agent_app.main:app", "--host", "0.0.0.0", "--port", "8000"]
