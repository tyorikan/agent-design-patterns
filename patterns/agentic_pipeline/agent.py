"""Agentic Pipeline パターン — ADK BaseAgent + Antigravity Agent。

ADK Workflow の条件付きエッジ（route）が ADK 2.1.0 では未実装のため、
BaseAgent を使って PGE ループを直接制御する。

各ノードの内部処理は Antigravity Agent（自律エージェント）に委任する。

認証: Vertex AI ADC のみ使用。

アーキテクチャ:
    PGEOrchestrator (BaseAgent)
        ├── run_planner_agent() → Antigravity Agent
        ├── run_generator_agent() → Antigravity Agent
        └── run_evaluator_agent() → Antigravity Agent
        └── ループ制御: REVISE → Planner に戻る

REVISE 条件:
    - score < 80 かつ改善可能 → REVISE（Planner に戻る）
    - score >= 80 → APPROVED
    - 最大反復到達 → 強制 APPROVED
    - 改善停滞（前回比 < 5点） → APPROVED
"""

import json
import logging

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types

from .tools import (
    run_evaluator_agent,
    run_generator_agent,
    run_planner_agent,
)

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 5


class _StateProxy:
    """ToolContext の最小限の代替。state 辞書へのアクセスを提供する。"""

    def __init__(self, state: dict):
        self.state = state


class PGEOrchestrator(BaseAgent):
    """Planner-Generator-Evaluator 3者間自律ループオーケストレーター。

    ADK Workflow の条件付きエッジ（route）が ADK 2.1.0 では未実装のため、
    BaseAgent で PGE ループを直接制御する。

    フロー:
        1. Planner: ユーザー要件から設計方針を策定
        2. Generator: 設計方針に基づきコードを実装
        3. Evaluator: コード品質を評価し、verdict を返す
        4. verdict == REVISE → 1 に戻る（最大 MAX_ITERATIONS 回）
        5. verdict == APPROVED → 終了
    """

    async def _run_async_impl(self, ctx: InvocationContext):
        """PGE ループを制御する。"""
        state = ctx.session.state
        tool_context = _StateProxy(state)

        # ユーザーメッセージを session events から取得
        user_request = ""
        for event in reversed(ctx.session.events):
            if (
                event.content
                and event.content.role == "user"
                and event.content.parts
            ):
                texts = [p.text for p in event.content.parts if p.text]
                if texts:
                    user_request = "\n".join(texts)
                    break
        state["user_request"] = user_request
        output_dir = state.get("output_dir", "")
        logger.info(
            "PGE Orchestrator: user_request=%s, output_dir=%s",
            user_request[:100],
            output_dir or "(default)",
        )

        for iteration in range(1, MAX_ITERATIONS + 1):
            logger.info(
                "PGE Orchestrator: Iteration %d/%d", iteration, MAX_ITERATIONS
            )

            # --- Planner ---
            yield Event(
                author=self.name,
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            text=f"[Iteration {iteration}] Planner を起動します..."
                        )
                    ],
                ),
            )

            plan = await run_planner_agent(
                user_request=state.get("user_request", ""),
                tool_context=tool_context,
            )
            state["plan"] = plan

            # --- Generator ---
            yield Event(
                author=self.name,
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            text=f"[Iteration {iteration}] Generator を起動します..."
                        )
                    ],
                ),
            )

            artifact = await run_generator_agent(
                plan=plan,
                tool_context=tool_context,
            )
            state["artifact"] = artifact

            # --- Evaluator ---
            yield Event(
                author=self.name,
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            text=f"[Iteration {iteration}] Evaluator を起動します..."
                        )
                    ],
                ),
            )

            result_text = await run_evaluator_agent(
                plan=plan,
                artifact=artifact,
                tool_context=tool_context,
            )
            state["evaluator_feedback"] = result_text

            # --- Verdict 判定 ---
            if result_text.startswith("APPROVED"):
                logger.info("PGE Orchestrator: APPROVED at iteration %d", iteration)
                yield Event(
                    author=self.name,
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part(
                                text=f"[Iteration {iteration}] ✅ APPROVED: {result_text}"
                            )
                        ],
                    ),
                )
                return

            logger.info("PGE Orchestrator: REVISE at iteration %d", iteration)
            yield Event(
                author=self.name,
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            text=f"[Iteration {iteration}] 🔄 REVISE: {result_text[:200]}"
                        )
                    ],
                ),
            )

        # 最大反復到達
        logger.warning(
            "PGE Orchestrator: Max iterations (%d) reached", MAX_ITERATIONS
        )
        yield Event(
            author=self.name,
            content=types.Content(
                role="model",
                parts=[
                    types.Part(
                        text=f"最大反復回数 ({MAX_ITERATIONS}) に到達しました。最終結果を返します。"
                    )
                ],
            ),
        )


root_agent = PGEOrchestrator(
    name="agentic_pipeline",
    description=(
        "汎用 PGE コード実装パイプライン。"
        "Antigravity Agent を頭脳とした Planner-Generator-Evaluator "
        "3者間自律レビューパイプライン。"
    ),
)
