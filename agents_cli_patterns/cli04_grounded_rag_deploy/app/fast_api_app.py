"""CLI-04: Cloud Run / Agent Runtime 対応 FastAPI エントリーポイント（ヘルスチェック付き）。"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from fastapi import FastAPI
from google.adk.cli.fast_api import get_fast_api_app

from .app_utils import services

load_dotenv()

AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
otel_to_cloud = os.environ.get("ENABLE_CLOUD_TELEMETRY", "").lower() in ("true", "1")

app: FastAPI = get_fast_api_app(
    agents_dir=AGENT_DIR,
    web=False,
    artifact_service_uri=services.ARTIFACT_SERVICE_URI,
    session_service_uri=services.SESSION_SERVICE_URI,
    otel_to_cloud=otel_to_cloud,
)
app.title = "cli04-grounded-rag-deploy"


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """ロードバランサ・コンテナランタイム向け軽量ヘルスチェック。"""
    return {
        "status": "ok",
        "llm_location": os.environ.get("GOOGLE_CLOUD_LOCATION", "global"),
        "session_region": services.resolve_session_region(),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8014")))
