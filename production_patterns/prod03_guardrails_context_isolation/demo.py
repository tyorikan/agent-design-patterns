"""PROD-03: Guardrails & Context Isolation パターン デモスクリプト。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from production_patterns.prod03_guardrails_context_isolation.agent import app
from shared.config import get_settings


async def main() -> None:
    """認証済みテナントコンテキスト下でチケット照会と請求確認を行うデモ。"""
    get_settings()
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name=app.name,
        user_id="demo-user",
        state={"auth:tenant_id": "tenant-alpha"},
    )
    runner = Runner(app=app, session_service=session_service)
    msg = types.Content(
        role="user",
        parts=[
            types.Part.from_text(
                text="外部チケット TKT-100 の内容を確認し、当テナントの未払い請求書を教えてください。"
            )
        ],
    )
    async for event in runner.run_async(
        user_id="demo-user", session_id=session.id, new_message=msg
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    print(part.text)


if __name__ == "__main__":
    asyncio.run(main())
