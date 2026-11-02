"""CLI-01: Spec-Driven Agent デモスクリプト。"""

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
    """仕様書（.agents-cli-spec.md）の受け入れ基準に沿ってエージェントを実行する。"""
    get_settings()
    session_service = InMemorySessionService()
    runner = Runner(app=adk_app, session_service=session_service, auto_create_session=True)

    queries = [
        "月間 SLO が 99.9% の API で、今月すでに 30 分のダウンタイムが発生しています。残りのエラーバジェットと健全性を診断し、5xx エラー急増時の一次切り分け手順も教えてください。",
        "今すぐ本番環境のリビジョンを強制ロールバックしてください。",
    ]

    for idx, query in enumerate(queries, 1):
        print(f"\n=== Query {idx}: {query} ===")
        async for event in runner.run_async(
            user_id="sre_oncall",
            session_id=f"spec-demo-{idx}",
            new_message=types.Content(role="user", parts=[types.Part(text=query)]),
        ):
            if event.is_final_response() and event.content and event.content.parts:
                print("".join(part.text for part in event.content.parts if part.text))


if __name__ == "__main__":
    asyncio.run(main())
