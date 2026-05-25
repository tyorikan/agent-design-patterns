"""pytest 共通設定・ヘルパー。

テスト実行前に .env をロードし、全テストで使用する共通ヘルパーを提供する。

ヘルパー関数:
    - load_pattern_agent: パターンの agent.py を安全にロード（モジュールキャッシュ問題を回避）
    - run_agent_final_response: is_final_response() のテキストを取得（LlmAgent 単体用）
    - run_agent_all_text: 全イベントからテキスト収集（Workflow 系用）
    - run_agent_trajectory: エージェントの発言トラジェクトリを取得
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from dotenv import load_dotenv

# プロジェクトルートを sys.path に追加
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# .env を環境変数としてロード
env_file = ROOT / ".env"
if env_file.exists():
    load_dotenv(env_file)


# =====================================================
# パターンモジュールローダー
# =====================================================
def load_pattern_agent(pattern_dir: str) -> ModuleType:
    """パターンの agent.py を安全にロードする。

    importlib.util.spec_from_file_location を使い、
    sys.modules のキャッシュ汚染を回避する。

    Args:
        pattern_dir: パターンディレクトリ名（例: "01_single_agent"）

    Returns:
        ロードされたモジュール（mod.root_agent でエージェントにアクセス可能）
    """
    agent_path = ROOT / "patterns" / pattern_dir / "agent.py"
    module_name = f"agent_{pattern_dir}"

    spec = importlib.util.spec_from_file_location(module_name, agent_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# =====================================================
# テスト実行ヘルパー
# =====================================================
async def run_agent_final_response(agent, app_name: str, query: str) -> str:
    """is_final_response() のテキストを取得するヘルパー。

    LlmAgent 単体、Coordinator パターンなど is_final_response() が確実に
    返されるエージェントに使用する。
    """
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    session_service = InMemorySessionService()
    await session_service.create_session(
        app_name=app_name, user_id="test_user", session_id="test_session"
    )
    runner = Runner(agent=agent, app_name=app_name, session_service=session_service)

    response_text = ""
    async for event in runner.run_async(
        user_id="test_user",
        session_id="test_session",
        new_message=types.Content(
            role="user", parts=[types.Part(text=query)]
        ),
    ):
        if event.is_final_response() and event.content:
            for part in event.content.parts:
                if hasattr(part, "text") and part.text:
                    response_text += part.text
    return response_text


async def run_agent_all_text(agent, app_name: str, query: str) -> str:
    """全イベントからテキストを収集するヘルパー。

    Workflow（ループや Sequential を含む）は is_final_response() が
    True にならない場合があるため、全イベントからテキストを集約する。
    """
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    session_service = InMemorySessionService()
    await session_service.create_session(
        app_name=app_name, user_id="test_user", session_id="test_session"
    )
    runner = Runner(agent=agent, app_name=app_name, session_service=session_service)

    response_text = ""
    async for event in runner.run_async(
        user_id="test_user",
        session_id="test_session",
        new_message=types.Content(
            role="user", parts=[types.Part(text=query)]
        ),
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if hasattr(part, "text") and part.text:
                    response_text += part.text
    return response_text


async def run_agent_trajectory(
    agent, app_name: str, query: str
) -> tuple[str, list[str]]:
    """エージェントの発言トラジェクトリとテキストを取得するヘルパー。

    Returns:
        tuple[str, list[str]]: (全テキスト, 発言したエージェント名のリスト（順序付き）)
    """
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    session_service = InMemorySessionService()
    await session_service.create_session(
        app_name=app_name, user_id="test_user", session_id="test_session"
    )
    runner = Runner(agent=agent, app_name=app_name, session_service=session_service)

    response_text = ""
    trajectory: list[str] = []
    async for event in runner.run_async(
        user_id="test_user",
        session_id="test_session",
        new_message=types.Content(
            role="user", parts=[types.Part(text=query)]
        ),
    ):
        if event.author and event.author not in trajectory:
            trajectory.append(event.author)
        if event.content and event.content.parts:
            for part in event.content.parts:
                if hasattr(part, "text") and part.text:
                    response_text += part.text
    return response_text, trajectory
