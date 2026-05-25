FROM python:3.12-slim

# uv をインストール
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# 依存関係ファイルをコピー
COPY pyproject.toml ./
COPY uv.lock* ./

# 依存関係をインストール（キャッシュ活用）
RUN uv sync --frozen --no-dev 2>/dev/null || uv sync --no-dev

# ソースコードをコピー
COPY . .

# 環境変数（デフォルト値）
ENV GOOGLE_GENAI_USE_VERTEXAI=True
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

EXPOSE 8080

CMD ["uv", "run", "adk", "web", "--host", "0.0.0.0", "--port", "8080"]
