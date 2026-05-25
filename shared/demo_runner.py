"""ADK エージェントのデモ実行共通ユーティリティ。"""

import asyncio
from typing import AsyncIterator

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()


async def run_agent_demo(
    agent: object,
    app_name: str,
    queries: list[str],
    user_id: str = "demo_user",
) -> None:
    """エージェントを複数のクエリで実行し、結果を表示する。

    Args:
        agent: ADK エージェント (root_agent)
        app_name: アプリケーション名
        queries: 実行するクエリのリスト
        user_id: ユーザー ID
    """
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name=app_name,
        user_id=user_id,
        session_id="demo_session",
    )

    runner = Runner(
        agent=agent,
        app_name=app_name,
        session_service=session_service,
    )

    for i, query in enumerate(queries, 1):
        console.print(Panel(
            f"[bold cyan]Query {i}/{len(queries)}[/bold cyan]\n{query}",
            border_style="cyan",
        ))

        response_text = ""
        async for event in runner.run_async(
            user_id=user_id,
            session_id="demo_session",
            new_message=types.Content(
                role="user",
                parts=[types.Part(text=query)],
            ),
        ):
            if event.is_final_response() and event.content:
                for part in event.content.parts:
                    if hasattr(part, "text") and part.text:
                        response_text += part.text

        console.print(Panel(
            Text(response_text, style="white"),
            title="[bold green]Response[/bold green]",
            border_style="green",
        ))
        console.print()


def run_demo(agent: object, app_name: str, queries: list[str]) -> None:
    """同期ラッパー。非同期デモを同期的に実行する。"""
    asyncio.run(run_agent_demo(agent, app_name, queries))
