"""ADK エージェント / ワークフローのデモ実行共通ユーティリティ。"""

import asyncio
import json

from google.adk.agents import BaseAgent
from google.adk.apps import App
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.workflow import BaseNode
from google.genai import types
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()


def _build_runner(
    target: App | BaseNode,
    app_name: str,
    session_service: InMemorySessionService,
) -> Runner:
    """`App` / `BaseAgent` / `BaseNode`（`Workflow`）に応じた `Runner` を構築する。"""
    if isinstance(target, App):
        return Runner(app=target, session_service=session_service)
    if isinstance(target, BaseAgent):
        return Runner(
            agent=target,
            app_name=app_name,
            session_service=session_service,
        )
    return Runner(
        node=target,
        app_name=app_name,
        session_service=session_service,
    )


async def run_agent_demo(
    agent: App | BaseNode,
    app_name: str,
    queries: list[str],
    user_id: str = "demo_user",
) -> None:
    """エージェントまたは Workflow を複数のクエリで実行し、結果を表示する。

    Args:
        agent: ADK の `App`、`BaseAgent`（`LlmAgent` 等）、または `BaseNode`（`Workflow` 等）
        app_name: アプリケーション名
        queries: 実行するクエリのリスト
        user_id: ユーザー ID
    """
    effective_app_name = agent.name if isinstance(agent, App) else app_name
    session_service = InMemorySessionService()
    await session_service.create_session(
        app_name=effective_app_name,
        user_id=user_id,
        session_id="demo_session",
    )
    runner = _build_runner(agent, effective_app_name, session_service)
    try:
        for i, query in enumerate(queries, 1):
            console.print(
                Panel(
                    f"[bold cyan]Query {i}/{len(queries)}[/bold cyan]\n{query}",
                    border_style="cyan",
                )
            )

            segments: list[tuple[str, str]] = []
            last_node_output: str = ""

            async for event in runner.run_async(
                user_id=user_id,
                session_id="demo_session",
                new_message=types.Content(
                    role="user",
                    parts=[types.Part(text=query)],
                ),
            ):
                if event.is_final_response() and event.content and event.content.parts:
                    chunk = "".join(
                        part.text
                        for part in event.content.parts
                        if part.text and not getattr(part, "thought", False)
                    )
                    if chunk.strip():
                        segments.append((event.author or "agent", chunk.strip()))
                if event.output is not None:
                    if isinstance(event.output, str):
                        last_node_output = event.output
                    else:
                        last_node_output = json.dumps(
                            event.output, ensure_ascii=False, indent=2, default=str
                        )

            if len(segments) > 1:
                response_text = "\n\n".join(
                    f"─── [{author}] ───\n{text}" for author, text in segments
                )
            elif len(segments) == 1:
                response_text = segments[0][1]
            else:
                response_text = last_node_output

            console.print(
                Panel(
                    Text(response_text, style="white"),
                    title="[bold green]Response[/bold green]",
                    border_style="green",
                )
            )
            console.print()
    finally:
        await runner.close()


def run_demo(agent: App | BaseNode, app_name: str, queries: list[str]) -> None:
    """同期ラッパー。非同期デモを同期的に実行する。"""
    asyncio.run(run_agent_demo(agent, app_name, queries))
