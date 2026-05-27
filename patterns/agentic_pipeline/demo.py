"""Agentic Pipeline デモ実行スクリプト。

汎用 PGE コード実装パイプラインを実行する。

使用方法:
    python patterns/agentic_pipeline/demo.py

前提条件:
    - Vertex AI ADC 認証が設定済み
    - .env に GOOGLE_CLOUD_PROJECT が設定済み
"""

import asyncio
import sys
from pathlib import Path

# プロジェクトルートを sys.path に追加
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from rich.console import Console

load_dotenv(ROOT / ".env")

console = Console()


async def main() -> None:
    """デモ実行のメインエントリーポイント。"""
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    from patterns.agentic_pipeline.agent import root_agent

    app_name = "agentic_pipeline_demo"
    user_id = "demo_user"
    session_id = "demo_session"

    session_service = InMemorySessionService()
    await session_service.create_session(
        app_name=app_name, user_id=user_id, session_id=session_id,
    )
    runner = Runner(
        agent=root_agent,
        app_name=app_name,
        session_service=session_service,
    )

    query = (
        "FastAPI で TODO アプリの REST API を実装してください。"
        "CRUD 操作（作成・一覧・更新・削除）、Pydantic バリデーション、"
        "pytest テスト付きでお願いします。"
    )

    console.print(f"\n[bold cyan]📋 ユーザー要件:[/] {query}\n")
    console.print("[bold yellow]🔄 Agentic Pipeline 実行中...[/]\n")

    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=types.Content(
            role="user", parts=[types.Part(text=query)],
        ),
    ):
        if event.content and event.content.parts:
            author = event.author or "system"
            for part in event.content.parts:
                if hasattr(part, "text") and part.text:
                    console.print(f"[dim]{author}:[/] {part.text[:500]}")

    console.print("\n[bold green]✅ Agentic Pipeline 完了[/]")


if __name__ == "__main__":
    asyncio.run(main())
