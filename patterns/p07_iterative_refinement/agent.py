"""Iterative Refinement Pattern - 自己改善型ドキュメント作成エージェント（Workflow v2）。

パターンの特徴:
    単一の `LlmAgent`（`doc_refiner`）が執筆と自己採点を行い、
    決定論的ルーター `@node`（`refinement_router`）が自己評価タグと最大反復回数（`MAX_ITERATIONS`）を
    検査して自己ループ（`REVISE` → `doc_refiner`）を制御する。

    Review & Critique (Lv.6) との違い:
    - Lv.6: Generator（生成）+ Critic（批評）の 2 役割を別エージェントに分離（独立性重視）
    - Lv.7: 1 エージェントが前回の出力と自己採点（`previous_doc_and_score`）を参照して自己改善（低コスト）
"""

import sys
from pathlib import Path
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.agents.context import Context
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.events.event import Event
from google.adk.workflow import Workflow, node
from google.genai import types

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.config import get_settings

settings = get_settings()

MAX_ITERATIONS = 5


def _extract_text(value: Any) -> str:
    """ノード入力からプレーンテキストを抽出する。"""
    if isinstance(value, str):
        return value
    if isinstance(value, types.Content) and value.parts:
        return "".join(
            p.text for p in value.parts if p.text and not getattr(p, "thought", False)
        )
    return str(value or "")


async def _build_doc_refiner_instruction(ctx: ReadonlyContext) -> str:
    """初回は新規作成、2 周目以降は前回のドキュメントと自己採点結果を参照して改善する。"""
    previous = ctx.state.get("previous_doc_and_score", "")
    iteration = int(ctx.state.get("refinement_iteration", 0)) + 1

    previous_section = ""
    if previous:
        previous_section = f"""
## 前回（第 {iteration - 1} 回）のドキュメントと自己採点結果
以下の減点理由をすべて解消し、前回より高い品質に改善してください:

{previous}
"""

    return f"""\
あなたは技術文書作成の専門家です。

## タスク: 技術ドキュメントの作成と改善（第 {iteration} 回）

ユーザーが指定したテーマについて、技術ドキュメントを作成・改善してください。
{previous_section}
---

## ドキュメント要件
- 対象読者: Google Cloud を学ぶエンジニア
- 構成: 概要、主要機能、ユースケース、始め方（コード例付き）、まとめ
- コードは Python または gcloud CLI を使用
- 図（ASCII アート）を含めること

## 自己評価（必須）

ドキュメントを作成後、以下の基準で自己採点してください:
- 技術的正確性 (30点): 内容の正確さ
- 網羅性 (25点): 重要な情報が含まれているか
- 読みやすさ (25点): 構成・文体・視覚的な見やすさ
- 実用性 (20点): コード例と実際の手順が使えるか

## 出力形式

---DOCUMENT---
[ドキュメント本文]
---SCORE---
総合スコア: XX/100
[各項目のスコアと理由]
判定: スコアが 85 以上なら `[COMPLETE]` 、未満なら `[CONTINUE]`
---END---
"""


# =====================================================
# ドキュメント改善エージェント（自己評価 + 改善）
# =====================================================
doc_refiner = LlmAgent(
    name="doc_refiner",
    model=settings.default_model,
    description="技術ドキュメントを自己評価しながら反復的に改善する",
    instruction=_build_doc_refiner_instruction,
    output_key="previous_doc_and_score",
)


# =====================================================
# 決定論的自己改善ルーター（@node）
# =====================================================
@node(name="refinement_router")
def refinement_router(ctx: Context, node_input: Any) -> Event:
    """自己評価タグ（`[COMPLETE]` / `[CONTINUE]`）と最大反復回数を検査して分岐する。"""
    iteration = int(ctx.state.get("refinement_iteration", 0)) + 1
    doc_and_score = _extract_text(node_input) or str(
        ctx.state.get("previous_doc_and_score", "")
    )
    upper = doc_and_score.upper()

    is_complete = "[COMPLETE]" in upper
    should_continue = ("[CONTINUE]" in upper or "REVISE" in upper) and not is_complete

    if should_continue and iteration < MAX_ITERATIONS:
        return Event(
            output=doc_and_score,
            route="REVISE",
            state={
                "refinement_iteration": iteration,
                "previous_doc_and_score": doc_and_score,
            },
        )
    return Event(
        output=doc_and_score,
        route="COMPLETE",
        state={
            "refinement_iteration": iteration,
            "previous_doc_and_score": doc_and_score,
        },
    )


@node(name="finalize_document")
def finalize_document(ctx: Context, node_input: Any) -> str:
    """完成したドキュメントと最終スコアを返す。"""
    return str(ctx.state.get("previous_doc_and_score") or _extract_text(node_input))


# =====================================================
# Workflow（条件付きサイクル - 自己ループ + 上限ガード）
# =====================================================
root_agent = Workflow(
    name="doc_refinement_loop",
    description="品質スコア 85 以上になるまで自己改善を繰り返す技術ドキュメント生成システム",
    edges=[
        (
            "START",
            doc_refiner,
            refinement_router,
            {"REVISE": doc_refiner, "COMPLETE": finalize_document},
        ),
    ],
)
