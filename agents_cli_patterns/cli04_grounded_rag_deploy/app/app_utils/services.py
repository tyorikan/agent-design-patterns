"""Cloud Run / Agent Runtime 本番サービング用 Session・Artifact サービス管理。

重要な設計ポイント:
    `gemini-4-hydrogen` は `GOOGLE_CLOUD_LOCATION=global` を必要とする一方、
    Agent Runtime のマネージドセッション（`VertexAiSessionService`）はリージョン指定
    （例: `us-central1`）を必要とする。そのため、セッション用ロケーションは
    `GOOGLE_CLOUD_AGENT_ENGINE_LOCATION` を優先参照し、`global` が誤って渡されないよう分離する。
"""

from __future__ import annotations

import functools
import os

from google.adk.artifacts import GcsArtifactService, InMemoryArtifactService
from google.adk.cli.service_registry import get_service_registry
from google.adk.cli.utils.service_factory import create_session_service_from_options
from google.adk.sessions.in_memory_session_service import InMemorySessionService

SESSION_SERVICE_URI = "shared://session"
ARTIFACT_SERVICE_URI = "shared://artifact"

_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def resolve_session_region() -> str:
    """セッションストア用のリージョンを解決する（`global` を回避してリージョンを返す）。"""
    if engine_loc := os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_LOCATION"):
        if engine_loc != "global":
            return engine_loc
    cloud_loc = os.environ.get("GOOGLE_CLOUD_LOCATION", "")
    if cloud_loc and cloud_loc != "global":
        return cloud_loc
    return "us-central1"


@functools.cache
def get_session_service():
    """環境変数に応じて URI 指定・Agent Runtime セッション・インメモリを切り替える。"""
    if uri := os.environ.get("SESSION_SERVICE_URI"):
        return create_session_service_from_options(base_dir=_AGENT_DIR, session_service_uri=uri)
    if agent_engine_id := os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ID"):
        from google.adk.sessions.vertex_ai_session_service import VertexAiSessionService

        return VertexAiSessionService(
            project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
            location=resolve_session_region(),
            agent_engine_id=agent_engine_id,
        )
    return InMemorySessionService()


@functools.cache
def get_artifact_service():
    """GCS バケット指定時は GcsArtifactService、未指定時は InMemoryArtifactService を返す。"""
    if bucket := os.environ.get("LOGS_BUCKET_NAME"):
        return GcsArtifactService(bucket_name=bucket)
    return InMemoryArtifactService()


_registry = get_service_registry()
_registry.register_session_service("shared", lambda uri, **kw: get_session_service())
_registry.register_artifact_service("shared", lambda uri, **kw: get_artifact_service())
