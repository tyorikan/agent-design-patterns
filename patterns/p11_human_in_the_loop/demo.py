"""Human-in-the-Loop デモ - ADK 2.x RequestInput によるコンテンツ承認ワークフロー。

`root_agent`（`ResumabilityConfig` 付き `App`）を実際に実行し、
`adk_request_input` 割り込みが発生した場合はコンソールから承認・却下を入力して
ワークフローを再開（Resume）する。
"""

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from patterns.p11_human_in_the_loop.agent import app  # noqa: E402

console = Console()

CONTENT_REQUEST = (
    "Gemini Enterprise Agent Platform を活用した社内業務自動化サービスの"
    "プロモーション原稿を作成してください（「導入初月から工数 80% 削減」という訴求案を含む）"
)


async def run_human_in_the_loop_demo() -> None:
    """Human-in-the-Loop ワークフローを実行し、必要時に人間の承認入力で再開する。"""
    session_service = InMemorySessionService()
    await session_service.create_session(
        app_name=app.name,
        user_id="demo_user",
        session_id="demo_session",
    )
    runner = Runner(app=app, session_service=session_service)

    console.print(
        Panel(
            f"[bold cyan]リクエスト:[/bold cyan]\n{CONTENT_REQUEST}",
            title="🚀 Step 1-2: 原稿生成 & コンプライアンス審査",
            border_style="cyan",
        )
    )

    pending_interrupt: types.FunctionCall | None = None
    async for event in runner.run_async(
        user_id="demo_user",
        session_id="demo_session",
        new_message=types.Content(
            role="user",
            parts=[types.Part.from_text(text=CONTENT_REQUEST)],
        ),
    ):
        for fc in event.get_function_calls():
            if fc.name == "adk_request_input":
                pending_interrupt = fc
        if event.is_final_response() and event.content and event.content.parts:
            text = "".join(
                p.text
                for p in event.content.parts
                if p.text and not getattr(p, "thought", False)
            )
            if text.strip():
                console.print(
                    Panel(
                        text.strip(),
                        title=f"[bold blue]{event.author}[/bold blue]",
                        border_style="blue",
                    )
                )

    if pending_interrupt is None:
        console.print(
            "\n[bold green]✅ コンプライアンス基準をクリアしたため、人間介入なしで自動公開されました。[/bold green]"
        )
        return

    prompt_msg = str((pending_interrupt.args or {}).get("message", "承認しますか？"))
    console.rule("[bold yellow]🧑 Step 3: Human-in-the-Loop 承認ゲート（一時停止中）[/bold yellow]")
    console.print(f"[yellow]{prompt_msg}[/yellow]\n")

    if sys.stdin.isatty():
        approved = Confirm.ask("このコンテンツの公開を承認しますか？", default=True)
    else:
        console.print("[dim]非対話環境のため既定値（APPROVE）で再開します。[/dim]")
        approved = True

    decision = (
        "APPROVE: 注意書きを添えて公開承認"
        if approved
        else "REJECT: 数値根拠の補足が必要なため差し戻し"
    )
    console.print(f"\n[bold]人間の判断:[/bold] {decision}\n")

    resume_message = types.Content(
        role="user",
        parts=[
            types.Part(
                function_response=types.FunctionResponse(
                    id=pending_interrupt.id,
                    name=pending_interrupt.name,
                    response={"result": decision},
                )
            )
        ],
    )

    async for event in runner.run_async(
        user_id="demo_user",
        session_id="demo_session",
        new_message=resume_message,
    ):
        if event.is_final_response() and event.content and event.content.parts:
            text = "".join(
                p.text
                for p in event.content.parts
                if p.text and not getattr(p, "thought", False)
            )
            if text.strip():
                console.print(
                    Panel(
                        text.strip(),
                        title=f"[bold green]再開結果 ({event.author})[/bold green]",
                        border_style="green" if approved else "red",
                    )
                )


if __name__ == "__main__":
    print("=" * 60)
    print("Lv.11 Human-in-the-Loop Pattern - コンテンツ承認ワークフロー")
    print("=" * 60)
    asyncio.run(run_human_in_the_loop_demo())
