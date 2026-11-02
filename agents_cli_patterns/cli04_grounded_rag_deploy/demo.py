"""CLI-04: Grounded RAG & Production Deploy デモスクリプト。"""

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
    """根拠ドキュメントがある場合と存在しない場合の両方でグラウンディング挙動を確認する。"""
    get_settings()
    runner = Runner(app=adk_app, session_service=InMemorySessionService(), auto_create_session=True)

    queries = [
        "決済 API のマルチリージョン DR における RPO / RTO 基準と冪等性要件を出典付きで教えてください。",
        "社内カフェテリアのランチ営業時間に関する規定を教えてください。",
    ]
    for idx, q in enumerate(queries, 1):
        print(f"\n=== Query {idx}: {q} ===")
        async for event in runner.run_async(
            user_id="architect_01",
            session_id=f"rag-demo-{idx}",
            new_message=types.Content(role="user", parts=[types.Part(text=q)]),
        ):
            if event.is_final_response() and event.content and event.content.parts:
                print("".join(part.text for part in event.content.parts if part.text))


if __name__ == "__main__":
    asyncio.run(main())
