"""Human-in-the-Loop デモ - コンテンツ承認ワークフロー。

人間の承認プロセスをコンソール入力でシミュレートする。
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")

from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm

from agent import compliance_checker, content_creator, final_publisher
from shared.config import get_settings

console = Console()
settings = get_settings()

CONTENT_REQUEST = "Google Cloud の Vertex AI を使った AI 開発サービスのプロモーションコンテンツ"


async def run_human_in_the_loop_demo() -> None:
    """Human-in-the-Loop ワークフローを段階的に実行する。"""
    session_service = InMemorySessionService()
    await session_service.create_session(
        app_name="hitl_workflow",
        user_id="user",
        session_id="session",
    )

    async def run_step(agent: LlmAgent, query: str, step_name: str) -> str:
        runner = Runner(
            agent=agent,
            app_name="hitl_workflow",
            session_service=session_service,
        )
        console.print(Panel(
            f"[bold cyan]実行中: {step_name}[/bold cyan]",
            border_style="cyan",
        ))
        response_text = ""
        async for event in runner.run_async(
            user_id="user",
            session_id="session",
            new_message=types.Content(
                role="user",
                parts=[types.Part(text=query)],
            ),
        ):
            if event.is_final_response() and event.content:
                for part in event.content.parts:
                    if hasattr(part, "text") and part.text:
                        response_text += part.text
        return response_text

    # Step 1: コンテンツ生成
    console.rule("[bold]Step 1: コンテンツ生成[/bold]")
    content = await run_step(
        content_creator,
        f"content_request: {CONTENT_REQUEST}",
        "コンテンツ生成エージェント",
    )
    console.print(Panel(content, title="生成されたコンテンツ", border_style="blue"))

    # Step 2: コンプライアンスチェック
    console.rule("[bold]Step 2: コンプライアンスチェック[/bold]")
    compliance = await run_step(
        compliance_checker,
        f"content_request: {CONTENT_REQUEST}\ngenerated_content: {content}",
        "コンプライアンスチェックエージェント",
    )
    console.print(Panel(compliance, title="コンプライアンスチェック結果", border_style="yellow"))

    # Step 3: Human-in-the-Loop（人間の判断）
    console.rule("[bold]Step 3: 🧑 Human Review（あなたが承認者です）[/bold]")
    console.print("[bold yellow]⚠️  人間のレビューが必要です。[/bold yellow]")
    console.print("上記のコンテンツとコンプライアンスチェック結果を確認してください。")

    approved = Confirm.ask("\nこのコンテンツを承認しますか？")

    human_decision = "✅ 承認済み - 人間レビュアーが承認しました" if approved else "❌ 否認 - 人間レビュアーが承認しませんでした。修正が必要です。"
    console.print(f"\n[bold]あなたの判断: {human_decision}[/bold]\n")

    if not approved:
        console.print("[red]ワークフロー終了: コンテンツは否認されました。[/red]")
        return

    # Step 4: 最終公開（承認された場合のみ）
    console.rule("[bold]Step 4: 最終公開処理[/bold]")
    final = await run_step(
        final_publisher,
        f"generated_content: {content}\ncompliance_result: {compliance}\nhuman_review: {human_decision}",
        "最終公開エージェント",
    )
    console.print(Panel(final, title="✅ 最終公開コンテンツ", border_style="green"))


if __name__ == "__main__":
    print("=" * 60)
    print("Lv.11 Human-in-the-Loop Pattern - コンテンツ承認ワークフロー")
    print("=" * 60)
    print("ワークフロー:")
    print("  1. 🤖 コンテンツ生成")
    print("  2. 🤖 コンプライアンスチェック")
    print("  3. 🧑 あなたの承認/否認 ← ここが Human-in-the-Loop!")
    print("  4. 🤖 最終公開処理")
    print()
    asyncio.run(run_human_in_the_loop_demo())
