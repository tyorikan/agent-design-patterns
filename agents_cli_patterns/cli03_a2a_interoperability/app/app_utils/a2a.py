"""FastAPI アプリケーションへ A2A（Agent2Agent）プロトコルのルートをマウントするユーティリティ。

`AgentCardBuilder` で ADK エージェント定義から動的に `AgentCard` を生成し、
`/.well-known/agent-card.json`（能力発見）と JSON-RPC エンドポイントを公開する。
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import (
    add_a2a_routes_to_fastapi,
    create_agent_card_routes,
    create_jsonrpc_routes,
)
from a2a.server.tasks import TaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentExtension, AgentInterface
from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH
from google.adk.a2a.executor.a2a_agent_executor import A2aAgentExecutor
from google.adk.a2a.utils.agent_card_builder import AgentCardBuilder

if TYPE_CHECKING:
    from fastapi import FastAPI
    from google.adk.agents import BaseAgent
    from google.adk.runners import Runner

_ADK_AGENT_EXECUTOR_EXTENSION_URI = "https://google.github.io/adk-docs/a2a/a2a-extension/"


def _add_v0_3_compat_interface(card: AgentCard) -> AgentCard:
    """A2A v1 に加え、v0.3 クライアントとの後方互換インターフェースを AgentCard に併記する。"""
    if card.supported_interfaces and not any(
        i.protocol_binding == "JSONRPC" and i.protocol_version == "0.3"
        for i in card.supported_interfaces
    ):
        card.supported_interfaces.append(
            AgentInterface(
                protocol_binding="JSONRPC",
                protocol_version="0.3",
                url=card.supported_interfaces[0].url,
            )
        )
    return card


def _default_capabilities() -> AgentCapabilities:
    """ストリーミングと ADK Executor 拡張を含む既定の A2A Capabilities を返す。"""
    return AgentCapabilities(
        streaming=True,
        extensions=[
            AgentExtension(
                uri=_ADK_AGENT_EXECUTOR_EXTENSION_URI,
                description="ADK A2aAgentExecutor integration",
            )
        ],
    )


async def attach_a2a_routes(
    app: FastAPI,
    *,
    agent: BaseAgent,
    runner: Runner,
    task_store: TaskStore,
    rpc_path: str,
    capabilities: AgentCapabilities | None = None,
    agent_version: str | None = None,
    app_url: str | None = None,
) -> AgentCard:
    """FastAPI インスタンスへ A2A AgentCard ルートと JSON-RPC ルートを登録する。"""
    resolved_app_url = app_url or os.getenv("APP_URL", "http://127.0.0.1:8000")
    resolved_version = agent_version or os.getenv("AGENT_VERSION", "0.1.0")
    resolved_capabilities = capabilities or _default_capabilities()

    agent_card = await AgentCardBuilder(
        agent=agent,
        capabilities=resolved_capabilities,
        rpc_url=f"{resolved_app_url}{rpc_path}",
        agent_version=resolved_version,
    ).build()
    agent_card = _add_v0_3_compat_interface(agent_card)

    request_handler = DefaultRequestHandler(
        agent_executor=A2aAgentExecutor(runner=runner, force_new_version=True),
        task_store=task_store,
        agent_card=agent_card,
    )

    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=create_agent_card_routes(
            agent_card,
            card_url=f"{rpc_path}{AGENT_CARD_WELL_KNOWN_PATH}",
        ),
        jsonrpc_routes=create_jsonrpc_routes(
            request_handler,
            rpc_url=rpc_path,
            enable_v0_3_compat=True,
        ),
    )
    return agent_card
