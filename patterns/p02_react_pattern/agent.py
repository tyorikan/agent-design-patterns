"""ReAct Pattern - Thought/Action/Observation ループを可視化するエージェント。

パターンの特徴:
    LlmAgent は内部的に ReAct ループを実行している。
    このコードでは ADK のイベントストリームを活用して、
    Thought → Action → Observation の各ステップを明示的に可視化する。

    ADK では runner.run_async() が返すイベントを解析することで
    ReAct ループの各フェーズ（Gemini 3.8 Flash のネイティブ思考パートを含む）を追跡できる。
"""

import ast
import operator
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

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

_BINARY_OPERATORS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}

_UNARY_OPERATORS: dict[type[ast.unaryop], Callable[[float], float]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_MAX_EXPONENT = 1000


def _eval_math_ast(node: ast.AST) -> float | int:
    """AST ノードを再帰的に評価し、安全な四則演算・べき乗のみを実行する。"""
    if isinstance(node, ast.Expression):
        return _eval_math_ast(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        if isinstance(node.value, bool):
            raise ValueError("真偽値は数式として使用できません")
        return node.value
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        operand = _eval_math_ast(node.operand)
        return _UNARY_OPERATORS[type(node.op)](operand)
    if isinstance(node, ast.BinOp):
        left = _eval_math_ast(node.left)
        right = _eval_math_ast(node.right)
        if isinstance(node.op, ast.Pow):
            if abs(right) > _MAX_EXPONENT:
                raise ValueError(f"指数が大きすぎます（上限: {_MAX_EXPONENT}）")
            result: Any = left**right
            if isinstance(result, complex):
                raise ValueError("複素数の結果はサポートされていません")
            return float(result) if isinstance(result, float) else int(result)
        op_fn = _BINARY_OPERATORS.get(type(node.op))
        if op_fn is not None:
            return op_fn(left, right)
    raise ValueError("許可されていない演算または構文が含まれています")


def calculate(expression: str) -> dict[str, str]:
    """数式を AST ベースで安全に計算します（`eval` 不使用）。

    Args:
        expression: 計算する数式（例: "100 * 1.08", "2 ** 10"）

    Returns:
        計算結果またはエラーメッセージを含む辞書
    """
    if "^" in expression:
        return {
            "error": "べき乗には '^'（ビット排他的論理和）ではなく '**' を使用してください",
        }
    try:
        parsed = ast.parse(expression.strip(), mode="eval")
        result = _eval_math_ast(parsed)
        return {"expression": expression, "result": str(result)}
    except ZeroDivisionError:
        return {"error": "ゼロ除算エラーが発生しました"}
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
- `calculate`: 数値計算（コスト試算、比率計算など。べき乗は `**` を使用）

## 回答形式
- 調査の過程（どの情報を、なぜ調べたか）を含めてください
- 最終的な回答は構造化されたレポート形式で
- 情報源となるURLを明記してください
""",
    tools=[google_search, calculate],
)


async def run_with_react_trace(query: str) -> None:
    """ReAct ループを可視化しながらエージェントを実行する。

    イベントストリームを解析して各フェーズ（Thought/Action/Observation/Final Answer）を表示する。
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

    console.print(
        Panel(
            f"[bold cyan]Query:[/bold cyan] {query}",
            title="🤔 ReAct Agent Starting",
            border_style="cyan",
        )
    )

    step = 0
    async for event in runner.run_async(
        user_id="user",
        session_id="session",
        new_message=types.Content(
            role="user",
            parts=[types.Part(text=query)],
        ),
    ):
        if not event.content or not event.content.parts:
            continue

        author = getattr(event, "author", "unknown")

        for part in event.content.parts:
            is_thought = bool(getattr(part, "thought", False))

            # Thought フェーズ（モデルのネイティブ思考パート、または中間ターンのテキスト）
            if part.text and (is_thought or not event.is_final_response()):
                step += 1
                console.print(f"\n[dim]Step {step} - 💭 Thought ({author}):[/dim]")
                console.print(f"  [italic]{part.text[:300]}[/italic]")

            # Action フェーズ（ツール呼び出し）
            elif part.function_call:
                step += 1
                fc = part.function_call
                console.print(f"\n[dim]Step {step} - ⚡ Action:[/dim]")
                console.print(f"  [bold yellow]Tool:[/bold yellow] {fc.name}")
                args_str = str(dict(fc.args or {}))[:200]
                console.print(f"  [bold yellow]Args:[/bold yellow] {args_str}")

            # Observation フェーズ（ツール結果）
            elif part.function_response:
                step += 1
                fr = part.function_response
                console.print(f"\n[dim]Step {step} - 👁️  Observation:[/dim]")
                response_str = str(fr.response)[:300]
                console.print(f"  [green]{response_str}...[/green]")

            # Final Response（最終回答本文）
            elif part.text and event.is_final_response():
                console.print(
                    Panel(
                        part.text,
                        title="[bold green]✅ Final Answer[/bold green]",
                        border_style="green",
                    )
                )

    console.print(f"\n[dim]Total ReAct steps: {step}[/dim]")
