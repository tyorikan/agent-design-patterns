"""CLI-02: Evaluation Gate パターン デモスクリプト。"""

import asyncio
import sys
from pathlib import Path

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

PROJECT_DIR = Path(__file__).resolve().parent
REPO_ROOT = PROJECT_DIR.parent.parent
for p in (str(PROJECT_DIR), str(REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from app.agent import app as adk_app  # noqa: E402

from shared.config import get_settings  # noqa: E402


async def main() -> None:
    """ゴールデン評価データセットと同等のシナリオを実行する。"""
    get_settings()
    runner = Runner(
        app=adk_app,
        session_service=InMemorySessionService(),
        auto_create_session=True,
    )
    query = (
        "LLM 推論コスト（llm_inference）が急増しています。原因と推奨アクションを調べた上で、"
        "現在の月額 $3,000 に推奨削減率を適用した場合の月間・年間削減額を試算してください。"
    )
    print(f"=== Query: {query} ===")
    async for event in runner.run_async(
        user_id="finops_lead",
        session_id="eval-gate-demo-1",
        new_message=types.Content(role="user", parts=[types.Part(text=query)]),
    ):
        if event.is_final_response() and event.content and event.content.parts:
            print("".join(part.text for part in event.content.parts if part.text))


if __name__ == "__main__":
    asyncio.run(main())
