"""CLI-03: ADK API + A2A JSON-RPC デュアルサービング FastAPI エントリーポイント。"""

from __future__ import annotations

import contextlib
import os
from collections.abc import AsyncIterator

from a2a.server.tasks import InMemoryTaskStore
from dotenv import load_dotenv
from fastapi import FastAPI
from google.adk.cli.fast_api import get_fast_api_app
from google.adk.runners import Runner

from .app_utils import services
from .app_utils.a2a import attach_a2a_routes

load_dotenv()

AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_a2a_attached = False


@contextlib.asynccontextmanager
async def lifespan(fastapi_app: FastAPI) -> AsyncIterator[None]:
    """起動時に Runner を初期化し、A2A エンドポイント（/a2a/app）をマウントする。"""
    global _a2a_attached
    from .agent import app as adk_app
    from .agent import root_agent

    runner = Runner(
        app=adk_app,
        session_service=services.get_session_service(),
        artifact_service=services.get_artifact_service(),
        auto_create_session=True,
    )
    fastapi_app.state.runner = runner
    fastapi_app.state.agent_app_name = adk_app.name

    if not _a2a_attached:
        card = await attach_a2a_routes(
            fastapi_app,
            agent=root_agent,
            runner=runner,
            task_store=InMemoryTaskStore(),
            rpc_path=f"/a2a/{adk_app.name}",
        )
        fastapi_app.state.agent_card = card
        _a2a_attached = True
    yield


app: FastAPI = get_fast_api_app(
    agents_dir=AGENT_DIR,
    web=False,
    artifact_service_uri=services.ARTIFACT_SERVICE_URI,
    session_service_uri=services.SESSION_SERVICE_URI,
    otel_to_cloud=False,
    lifespan=lifespan,
)
app.title = "cli03-a2a-interoperability"
app.description = "Security Advisory Agent serving both ADK REST/SSE and A2A JSON-RPC"


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8013)
