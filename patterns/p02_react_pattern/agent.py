"""ReAct Pattern - Thought/Action/Observation ループを可視化するエージェント。

パターンの特徴:
    LlmAgent は内部的に ReAct ループを実行している。
    このコードでは ADK のイベントストリームを活用して、
    Thought → Action → Observation の各ステップを明示的に可視化する。

    ADK では runner.run_async() が返すイベントを解析することで
    ReAct ループの各フェーズを追跡できる。
"""

import asyncio
import sys
from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import google_search
from google.genai import types
from rich.console import Console
from rich.panel import Panel

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.config import get_settings

settings = get_settings()
console = Console()


def calculate(expression: str) -> dict[str, str]:
    """数式を計算します（安全な評価）。

    Args:
        expression: 計算する数式（例: "100 * 1.08", "2 ** 10"）

    Returns:
        計算結果を含む辞書
    """
    try:
        # 安全な文字のみ許可
        allowed_chars = set("0123456789+-*/().^ ")
        if not all(c in allowed_chars for c in expression):
            return {"error": "使用できない文字が含まれています"}
        result = eval(expression)  # noqa: S307 (意図的なシンプル実装)
        return {"expression": expression, "result": str(result)}
    except Exception as e:
        return {"error": str(e)}


# =====================================================
# ReAct パターンの定義
# =====================================================
# LlmAgent は内部的に ReAct ループを実装している。
# Single Agent (Lv.1) との違いは「イベントストリームを解析して
# 思考プロセスを可視化する」点にある。
# =====================================================
root_agent = LlmAgent(
    name="research_react_agent",
    model=settings.default_model,
    description="Thought→Action→Observation ループで段階的に問題を解析するリサーチエージェント",
    instruction="""
あなたは分析的なリサーチエージェントです。
問題を段階的に考え、必要な情報を収集しながら詳細な分析を提供してください。

## 思考プロセス（ReAct ループ）
各ステップで以下を明確にしてください:
1. **Thought**: 次に何を調べるべきか、なぜそれが必要かを説明
2. **Action**: 適切なツールを使って情報を収集
3. **Observation**: 得られた結果を評価し、次のアクションを決定

## ツール
- `google_search`: 最新情報の検索。複数の観点から検索してください
- `calculate`: 数値計算（コスト試算、比率計算など）

## 回答形式
- 調査の過程（どの情報を、なぜ調べたか）を含めてください
- 最終的な回答は構造化されたレポート形式で
- 情報源となるURLを明記してください
""",
    tools=[google_search, calculate],
)


async def run_with_react_trace(query: str) -> None:
    """ReAct ループを可視化しながらエージェントを実行する。

    イベントストリームを解析して各フェーズ（Thought/Action/Observation）を表示。
    """
    session_service = InMemorySessionService()
    await session_service.create_session(
        app_name="react_agent",
        user_id="user",
        session_id="session",
    )

    runner = Runner(
        agent=root_agent,
        app_name="react_agent",
        session_service=session_service,
    )

    console.print(Panel(
        f"[bold cyan]Query:[/bold cyan] {query}",
        title="🤔 ReAct Agent Starting",
        border_style="cyan",
    ))

    step = 0
    async for event in runner.run_async(
        user_id="user",
        session_id="session",
        new_message=types.Content(
            role="user",
            parts=[types.Part(text=query)],
        ),
    ):
        if not event.content:
            continue

        author = getattr(event, "author", "unknown")

        for part in event.content.parts:
            # Thought フェーズ（テキスト思考）
            if hasattr(part, "text") and part.text and not event.is_final_response():
                step += 1
                console.print(f"\n[dim]Step {step} - 💭 Thought ({author}):[/dim]")
                console.print(f"  [italic]{part.text[:300]}[/italic]")

            # Action フェーズ（ツール呼び出し）
            elif hasattr(part, "function_call") and part.function_call:
                step += 1
                fc = part.function_call
                console.print(f"\n[dim]Step {step} - ⚡ Action:[/dim]")
                console.print(f"  [bold yellow]Tool:[/bold yellow] {fc.name}")
                args_str = str(dict(fc.args))[:200]
                console.print(f"  [bold yellow]Args:[/bold yellow] {args_str}")

            # Observation フェーズ（ツール結果）
            elif hasattr(part, "function_response") and part.function_response:
                step += 1
                fr = part.function_response
                console.print(f"\n[dim]Step {step} - 👁️  Observation:[/dim]")
                response_str = str(fr.response)[:300]
                console.print(f"  [green]{response_str}...[/green]")

            # Final Response
            elif hasattr(part, "text") and part.text and event.is_final_response():
                console.print(Panel(
                    part.text,
                    title="[bold green]✅ Final Answer[/bold green]",
                    border_style="green",
                ))

    console.print(f"\n[dim]Total ReAct steps: {step}[/dim]")
