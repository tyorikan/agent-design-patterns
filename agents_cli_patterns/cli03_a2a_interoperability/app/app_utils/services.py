"""ADK Web API と A2A エンドポイント間でプロセス内サービス（Session / Artifact）を共有するモジュール。

`shared://` スキームを ADK の ServiceRegistry に登録することで、
`/run_sse`（ADK ネイティブ）と `/a2a/app`（A2A JSON-RPC）が同一のセッションストアを参照できる。
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


@functools.cache
def get_session_service():
    """プロセス全体で共有する SessionService を返す。"""
    if uri := os.environ.get("SESSION_SERVICE_URI"):
        return create_session_service_from_options(base_dir=_AGENT_DIR, session_service_uri=uri)
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
