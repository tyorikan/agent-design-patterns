FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# 非 root 実行ユーザーの作成（本番コンテナの最小権限原則）
RUN useradd --create-home --uid 10001 agentuser
WORKDIR /app

COPY pyproject.toml ./
RUN uv pip install --system --no-cache \
    "google-adk>=2.13.0" \
    "google-genai>=2.34.0" \
    "fastapi>=0.124.1" \
    "uvicorn>=0.34.0" \
    "httpx>=0.27.0"

COPY app ./app
COPY agents-cli-manifest.yaml AGENTS.md .agents-cli-spec.md ./

ENV GOOGLE_GENAI_USE_ENTERPRISE=True
ENV GOOGLE_CLOUD_LOCATION=global
ENV GOOGLE_CLOUD_AGENT_ENGINE_LOCATION=us-central1
ENV PORT=8080
ENV PYTHONUNBUFFERED=1

USER agentuser
EXPOSE 8080

CMD ["sh", "-c", "uvicorn app.fast_api_app:app --host 0.0.0.0 --port ${PORT:-8080}"]
