---
name: adk-testing-debugging
description: |
  Google ADK エージェントのテスト・デバッグ・観測可能性のスキル。
  pytest を使ったユニットテスト・統合テストの書き方、
  ADK のイベントストリームのデバッグ方法、
  Cloud Logging/Tracing との統合パターンを提供する。
  エージェント実装のテスト・デバッグ時に参照すること。
---

# ADK テスト・デバッグスキル

## ユニットテスト

```python
# tests/test_agent.py
import pytest
from unittest.mock import patch, AsyncMock
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from my_agent.agent import root_agent


@pytest.fixture
async def runner():
    """テスト用 Runner を提供するフィクスチャ"""
    session_service = InMemorySessionService()
    await session_service.create_session(
        app_name="test_app",
        user_id="test_user",
        session_id="test_session"
    )
    return Runner(
        agent=root_agent,
        app_name="test_app",
        session_service=session_service
    )


async def run_agent(runner: Runner, message: str) -> str:
    """エージェントを実行して最終レスポンスを取得するヘルパー"""
    response_text = ""
    async for event in runner.run_async(
        user_id="test_user",
        session_id="test_session",
        new_message=types.Content(
            role="user",
            parts=[types.Part(text=message)]
        )
    ):
        if event.is_final_response():
            response_text = event.content.parts[0].text
    return response_text


@pytest.mark.asyncio
async def test_agent_responds(runner):
    """エージェントが応答することを確認"""
    response = await run_agent(runner, "こんにちは")
    assert response != ""
    assert isinstance(response, str)


@pytest.mark.asyncio
async def test_agent_uses_tool(runner):
    """エージェントがツールを使用することを確認"""
    with patch("my_agent.tools.get_weather") as mock_tool:
        mock_tool.return_value = {"city": "Tokyo", "temp": 25}
        
        response = await run_agent(runner, "東京の天気は？")
        mock_tool.assert_called_once()
        assert "東京" in response or "Tokyo" in response
```

## 統合テスト（セッション状態の検証）

```python
@pytest.mark.asyncio
async def test_session_state_preserved(runner):
    """セッション状態が適切に保存されることを確認"""
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name="test", user_id="user", session_id="sess"
    )
    
    runner_with_state = Runner(
        agent=pipeline_agent,
        app_name="test",
        session_service=session_service
    )
    
    await run_agent(runner_with_state, "データを処理してください")
    
    # セッション状態を検証
    updated_session = await session_service.get_session(
        app_name="test", user_id="user", session_id="sess"
    )
    assert "processed_data" in updated_session.state
```

## デバッグ: イベントストリームの詳細表示

```python
import json

async def debug_agent_run(runner: Runner, message: str):
    """デバッグ用: 全イベントを詳細表示"""
    async for event in runner.run_async(
        user_id="user",
        session_id="session",
        new_message=types.Content(
            role="user",
            parts=[types.Part(text=message)]
        )
    ):
        # イベントタイプを表示
        print(f"\n{'='*50}")
        print(f"Event type: {type(event).__name__}")
        print(f"Author: {event.author}")
        
        if hasattr(event, 'content') and event.content:
            for part in event.content.parts:
                if hasattr(part, 'text') and part.text:
                    print(f"Text: {part.text[:200]}...")
                if hasattr(part, 'function_call') and part.function_call:
                    print(f"Tool call: {part.function_call.name}")
                    print(f"Args: {json.dumps(dict(part.function_call.args), indent=2)}")
                if hasattr(part, 'function_response') and part.function_response:
                    print(f"Tool response: {part.function_response.name}")
        
        if event.is_final_response():
            print("\n✅ Final Response!")
```

## ツールのモック

```python
# conftest.py
import pytest
from unittest.mock import patch

@pytest.fixture
def mock_search():
    """Google Search のモック"""
    with patch("google.adk.tools.google_search") as mock:
        mock.return_value = [
            {"title": "テスト結果", "snippet": "テスト内容", "url": "https://example.com"}
        ]
        yield mock

@pytest.fixture  
def mock_external_api():
    """外部 API のモック"""
    with patch("my_agent.tools.call_external_api") as mock:
        mock.return_value = {"status": "success", "data": {"key": "value"}}
        yield mock
```

## 観測可能性（Cloud Logging）

```python
import logging
import json
from google.cloud import logging as cloud_logging
from google.adk.agents.callback_context import CallbackContext
from google.adk.tools import ToolContext

# Cloud Logging セットアップ
cloud_logging.Client().setup_logging()
logger = logging.getLogger(__name__)

def log_model_call_callback(callback_context: CallbackContext):
    """モデル呼び出しをログに記録"""
    logger.info(
        "model_call",
        extra={
            "json_fields": {
                "agent_name": callback_context.agent_name,
                "session_id": callback_context.session_id,
                "event_type": "model_call",
            }
        }
    )

def log_tool_response_callback(tool, args, context, response):
    """ツール実行結果をログに記録"""
    logger.info(
        "tool_execution",
        extra={
            "json_fields": {
                "tool_name": tool.name,
                "args": args,
                "success": response is not None,
            }
        }
    )
    return None  # 元のレスポンスを使用
```

## ADK v2: Workflow のテスト

> **重要**: ADK v2 では `Workflow` は `BaseAgent` ではなく `BaseNode` のサブクラス。
> `Runner` には直接渡せるが、`sub_agents` には入れられない。
> また `LoopAgent` は廃止され、`Workflow` の条件付きサイクル（`dict` による条件付きエッジ）に置き換わった。

```python
# tests/test_workflow.py
import pytest
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.workflow import Workflow
from google.genai import types


@pytest.fixture
async def workflow_runner():
    """Workflow 用テスト Runner"""
    session_service = InMemorySessionService()
    await session_service.create_session(
        app_name="test_app",
        user_id="test_user",
        session_id="test_session",
    )

    # 条件付きサイクル（旧 LoopAgent 相当）のテスト
    workflow = Workflow(
        name="review_loop",
        edges=[
            ("START", drafter, reviewer, {"REVISE": drafter}),
        ],
    )

    return Runner(
        agent=workflow,
        app_name="test_app",
        session_service=session_service,
    )


@pytest.mark.asyncio
async def test_workflow_completes(workflow_runner):
    """Workflow が最終的に完了することを確認"""
    response_text = ""
    async for event in workflow_runner.run_async(
        user_id="test_user",
        session_id="test_session",
        new_message=types.Content(
            role="user",
            parts=[types.Part(text="レポートを作成してください")],
        ),
    ):
        if event.is_final_response():
            response_text = event.content.parts[0].text
    assert response_text != ""
```

---

## pytest.ini / pyproject.toml 設定

```toml
# pyproject.toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
python_files = ["test_*.py"]
python_functions = ["test_*"]

[tool.mypy]
python_version = "3.12"
strict = true
ignore_missing_imports = true

[tool.ruff]
line-length = 100
select = ["E", "F", "I"]
```
