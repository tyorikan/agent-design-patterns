"""pytest 共通設定・ヘルパー。

テスト実行前に .env をロードし、全 3 トラック（`patterns/`, `agents_cli_patterns/`, `production_patterns/`）で
使用する共通ヘルパーを提供する。

ヘルパー関数:
    - load_pattern_agent: `patterns/<dir>/agent.py` をロード
    - load_cli_pattern_agent: `agents_cli_patterns/<dir>/app/agent.py` をロード
    - load_production_pattern_agent: `production_patterns/<dir>/agent.py` をロード
    - run_agent_final_response: is_final_response() のテキストを取得（LlmAgent 単体用）
    - run_agent_all_text: 全イベントからテキスト収集（Workflow 系用）
    - run_agent_trajectory: エージェントの発言トラジェクトリと出力を取得
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from dotenv import load_dotenv

# プロジェクトルートを sys.path に追加
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# .env を環境変数としてロード
env_file = ROOT / ".env"
if env_file.exists():
    load_dotenv(env_file)


def pytest_configure(config: pytest.Config) -> None:
    """オフラインのユニットテスト実行時に未設定の GOOGLE_CLOUD_PROJECT を補完する。

    統合テスト（`tests/integration`）実行時は実際の Google Cloud プロジェクト指定を必須とするため、
    ダミー値は設定しない。
    """
    collect_only = bool(config.getoption("--collect-only", default=False))
    args_str = " ".join(str(a) for a in config.args)
    is_integration = ("integration" in args_str or not config.args) and not collect_only
    if not is_integration:
        os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "unit-test-project")
        os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
        os.environ.setdefault("GOOGLE_GENAI_USE_ENTERPRISE", "True")
        os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")


# =====================================================
# パターンモジュールローダー（3 トラック対応）
# =====================================================
def load_pattern_agent(pattern_dir: str) -> ModuleType:
    """`patterns/<pattern_dir>/agent.py` をパッケージとして安全にロードする。"""
    return importlib.import_module(f"patterns.{pattern_dir}.agent")


def load_cli_pattern_agent(pattern_dir: str) -> ModuleType:
    """`agents_cli_patterns/<pattern_dir>/app/agent.py` をパッケージとしてロードする。"""
    return importlib.import_module(f"agents_cli_patterns.{pattern_dir}.app.agent")


def load_production_pattern_agent(pattern_dir: str) -> ModuleType:
    """`production_patterns/<pattern_dir>/agent.py` をパッケージとしてロードする。"""
    return importlib.import_module(f"production_patterns.{pattern_dir}.agent")


def _create_runner(
    target: Any,
    app_name: str,
    session_service: Any,
    artifact_service: Any = None,
) -> Any:
    """`App` / `BaseAgent` / `BaseNode`（`Workflow`）のいずれに対しても適切な `Runner` を生成する。"""
    from google.adk.agents import BaseAgent
    from google.adk.apps import App
    from google.adk.runners import Runner

    if isinstance(target, App):
        return Runner(
            app=target,
            session_service=session_service,
            artifact_service=artifact_service,
        )
    if isinstance(target, BaseAgent):
        return Runner(
            agent=target,
            app_name=app_name,
            session_service=session_service,
            artifact_service=artifact_service,
        )
    return Runner(
        node=target,
        app_name=app_name,
        session_service=session_service,
        artifact_service=artifact_service,
    )


# =====================================================
# テスト実行ヘルパー
# =====================================================
async def run_agent_final_response(
    agent: Any,
    app_name: str,
    query: str,
    initial_state: dict[str, Any] | None = None,
) -> str:
    """`is_final_response()` のテキストを取得するヘルパー（`LlmAgent` / `App` 用）。"""
    from google.adk.apps import App
    from google.adk.artifacts import InMemoryArtifactService
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    effective_app_name = agent.name if isinstance(agent, App) else app_name
    session_service = InMemorySessionService()
    artifact_service = InMemoryArtifactService()
    await session_service.create_session(
        app_name=effective_app_name,
        user_id="test_user",
        session_id="test_session",
        state=initial_state,
    )
    runner = _create_runner(agent, effective_app_name, session_service, artifact_service)

    response_text = ""
    async for event in runner.run_async(
        user_id="test_user",
        session_id="test_session",
        new_message=types.Content(role="user", parts=[types.Part(text=query)]),
    ):
        if event.is_final_response() and event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    response_text += part.text
    return response_text


async def run_agent_all_text(
    agent: Any,
    app_name: str,
    query: str,
    initial_state: dict[str, Any] | None = None,
) -> str:
    """全イベントからテキストおよび `Workflow` ノード出力を収集するヘルパー。"""
    response_text, _ = await run_agent_trajectory(
        agent, app_name, query, initial_state=initial_state
    )
    return response_text


async def run_agent_trajectory(
    agent: Any,
    app_name: str,
    query: str,
    initial_state: dict[str, Any] | None = None,
) -> tuple[str, list[str]]:
    """エージェントの発言トラジェクトリとテキスト（およびノード構造化出力）を取得するヘルパー。"""
    from google.adk.apps import App
    from google.adk.artifacts import InMemoryArtifactService
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    effective_app_name = agent.name if isinstance(agent, App) else app_name
    session_service = InMemorySessionService()
    artifact_service = InMemoryArtifactService()
    await session_service.create_session(
        app_name=effective_app_name,
        user_id="test_user",
        session_id="test_session",
        state=initial_state,
    )
    runner = _create_runner(agent, effective_app_name, session_service, artifact_service)

    response_text = ""
    trajectory: list[str] = []
    async for event in runner.run_async(
        user_id="test_user",
        session_id="test_session",
        new_message=types.Content(role="user", parts=[types.Part(text=query)]),
    ):
        if event.author and event.author not in trajectory:
            trajectory.append(event.author)
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    response_text += part.text
        if event.output is not None:
            response_text += "\n" + json.dumps(event.output, ensure_ascii=False, default=str)
    return response_text, trajectory
