FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen

COPY src ./src
COPY README.md main.py ./

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "iam_agent.api.orch_routes:app", "--host", "0.0.0.0", "--port", "8000"]

