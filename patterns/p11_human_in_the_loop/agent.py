"""Human-in-the-Loop Pattern - コンテンツ承認ワークフロー（ADK 2.x RequestInput 版）。

パターンの特徴:
    高リスク判定時や法的判断が必要な場面でワークフローを決定論的に一時停止（Interrupt）し、
    人間の明示的な承認（Approve）または却下（Reject）を受け取ってから再開（Resume）するパターン。

ADK 2.13 実装アーキテクチャ:
    1. `content_creator` (`LlmAgent`): ユーザー要求からマーケティング原稿を生成（`generated_content`）
    2. `compliance_checker` (`LlmAgent`): 法務・表現リスクを審査（`compliance_result`）
    3. `compliance_router` (`@node`):
       - `[AUTO_APPROVED]` 判定時 → 人間介入なしで `final_publisher` へ直行
       - `[HUMAN_REVIEW_REQUIRED]` / `[REJECTED]` 判定時 → `human_review_gate` へ遷移
    4. `human_review_gate` (`@node(rerun_on_resume=True)`):
       - 初回実行時に `RequestInput` イベントを発行してワークフローを中断
       - 再開時に人間の応答（`APPROVE` / `REJECT`）を読み取り、`final_publisher` または `rejection_notifier` へ分岐
"""

import sys
import warnings
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.agents.context import Context
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.apps import App, ResumabilityConfig
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.workflow import Workflow, node
from google.genai import types

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.config import get_settings

settings = get_settings()

HUMAN_REVIEW_INTERRUPT_ID = "compliance_human_review"


def _extract_text(value: Any) -> str:
    """ノード入力からプレーンテキストを抽出する。"""
    if isinstance(value, str):
        return value
    if isinstance(value, types.Content) and value.parts:
        return "".join(
            p.text for p in value.parts if p.text and not getattr(p, "thought", False)
        )
    return str(value or "")


# =====================================================
# Step 1: コンテンツ生成エージェント
# =====================================================
content_creator = LlmAgent(
    name="content_creator",
    model=settings.default_model,
    description="マーケティングコンテンツを生成する",
    instruction="""
あなたはマーケティングコピーライターです。
ユーザーのリクエストに基づいてマーケティングコンテンツを生成してください。

## 作成するコンテンツ
1. **見出し** (50文字以内)
2. **リード文** (100文字以内、核心的なベネフィット)
3. **本文** (300文字程度、3つの主要ポイント)
4. **CTA** (コールトゥアクション、20文字以内)

## ガイドライン
- 誇大広告は禁止
- 競合他社の名指し批判は禁止
- 個人情報や機密情報を含めない
- 事実に基づいた記述のみ

コンテンツを生成したら、コンプライアンスリスクの自己評価も記載してください:
- リスクレベル: 低/中/高
- リスク要因（あれば）
""",
    output_key="generated_content",
)


# =====================================================
# Step 2: コンプライアンスチェックエージェント
# =====================================================
async def _build_compliance_instruction(ctx: ReadonlyContext) -> str:
    """生成されたコンテンツを安全に参照してコンプライアンス審査を行う。"""
    draft = ctx.state.get("generated_content", "（コンテンツ未生成）")
    return f"""
あなたはコンプライアンスオフィサーです。
以下のマーケティングコンテンツを審査してください。

## 審査対象コンテンツ
{draft}

## 審査項目
1. **法的リスク**: 景品表示法、薬機法など法令違反の可能性
2. **誇大表現**: 根拠のない最上級表現（「最高」「唯一」「100%保証」など）
3. **差別・偏見**: 特定グループへの差別的表現
4. **プライバシー**: 個人情報・機密情報の漏洩リスク
5. **競合への言及**: 不適切な競合比較

## 判定結果フォーマット

### 審査スコア: XX/100

### リスク項目
（問題がある場合は具体的に記述）

### 承認ステータス（以下のいずれか 1 つを必ず角括弧付きで記載）
- スコア 85 以上かつ高リスク項目なし → `[AUTO_APPROVED]`
- スコア 70〜84 または中リスク → `[HUMAN_REVIEW_REQUIRED]`
- スコア 70 未満または高リスク → `[REJECTED]`

### 推奨アクション
"""


compliance_checker = LlmAgent(
    name="compliance_checker",
    model=settings.default_model,
    description="コンテンツのコンプライアンスチェックを行う",
    instruction=_build_compliance_instruction,
    output_key="compliance_result",
)


# =====================================================
# Step 3: コンプライアンス判定ルーター（@node）
# =====================================================
@node(name="compliance_router")
def compliance_router(ctx: Context, node_input: Any) -> Event:
    """審査結果を解析し、自動承認か人間レビュー要求かを決定論的にルーティングする。"""
    compliance_text = _extract_text(node_input) or str(
        ctx.state.get("compliance_result", "")
    )
    upper = compliance_text.upper()

    is_auto_approved = (
        "[AUTO_APPROVED]" in upper
        and "[HUMAN_REVIEW_REQUIRED]" not in upper
        and "[REJECTED]" not in upper
    )
    if is_auto_approved:
        return Event(
            output=compliance_text,
            route="AUTO_APPROVED",
            state={
                "compliance_result": compliance_text,
                "human_review": "自動承認（コンプライアンス基準クリア・人間介入不要）",
            },
        )
    return Event(
        output=compliance_text,
        route="HUMAN_REVIEW_REQUIRED",
        state={"compliance_result": compliance_text},
    )


# =====================================================
# Step 4: 人間承認ゲート（RequestInput による一時停止と再開）
# =====================================================
@node(name="human_review_gate", rerun_on_resume=True)
async def human_review_gate(
    ctx: Context,
    node_input: Any,
) -> AsyncGenerator[RequestInput | Event, None]:
    """初回実行時は `RequestInput` で一時停止し、再開時は人間の判断に応じて分岐する。"""
    draft = str(ctx.state.get("generated_content", ""))
    compliance_text = _extract_text(node_input) or str(
        ctx.state.get("compliance_result", "")
    )

    if not ctx.resume_inputs or HUMAN_REVIEW_INTERRUPT_ID not in ctx.resume_inputs:
        yield RequestInput(
            interrupt_id=HUMAN_REVIEW_INTERRUPT_ID,
            message=(
                "コンプライアンス審査で人間による承認が要求されました。"
                "公開を承認する場合は 'APPROVE'、却下する場合は 'REJECT' と理由を入力してください。"
            ),
            payload={
                "generated_content": draft,
                "compliance_result": compliance_text,
            },
        )
        return

    raw_reply = ctx.resume_inputs[HUMAN_REVIEW_INTERRUPT_ID]
    if isinstance(raw_reply, dict):
        decision_str = str(
            raw_reply.get("result") or raw_reply.get("decision") or raw_reply
        ).strip()
    else:
        decision_str = str(raw_reply).strip()

    upper = decision_str.upper()
    is_approved = (
        upper.startswith("APPROVE")
        or upper in {"Y", "YES", "OK", "TRUE"}
        or ("承認" in decision_str and "否認" not in decision_str and "却下" not in decision_str)
    )

    if is_approved:
        yield Event(
            output=decision_str,
            route="APPROVED",
            state={"human_review": f"人間レビュアー承認: {decision_str}"},
        )
    else:
        yield Event(
            output=decision_str,
            route="REJECTED",
            state={"human_review": f"人間レビュアー却下: {decision_str}"},
        )


# =====================================================
# Step 5A: 最終公開エージェント（承認時）
# =====================================================
async def _build_publisher_instruction(ctx: ReadonlyContext) -> str:
    """承認済みコンテンツとレビュー記録を統合して公開フォーマットに整形する。"""
    draft = ctx.state.get("generated_content", "（コンテンツなし）")
    compliance = ctx.state.get("compliance_result", "（審査記録なし）")
    human_review = ctx.state.get("human_review", "承認済み")
    return f"""
あなたはコンテンツマネージャーです。
承認済みのコンテンツを最終形式にまとめてください。

## コンテンツ
{draft}

## コンプライアンス審査結果
{compliance}

## 承認記録
{human_review}

最終的に承認されたコンテンツを以下の形式で出力してください:

---
# 📢 公開承認済みコンテンツ

## メタデータ
- 承認ステータス: 承認済み
- レビュー記録: {human_review}

## 公開コンテンツ
[コンテンツ本文]

## 公開チャンネル推奨
[最適な配信チャンネルの提案]
---
"""


final_publisher = LlmAgent(
    name="final_publisher",
    model=settings.default_model,
    description="承認済みコンテンツを最終形式で出力する",
    instruction=_build_publisher_instruction,
)


# =====================================================
# Step 5B: 却下通知ノード（人間却下時 — 公開処理を確実に抑止）
# =====================================================
@node(name="rejection_notifier")
def rejection_notifier(ctx: Context, node_input: Any) -> AsyncGenerator[Event, None] | Any:
    """人間レビュアーにより却下された際、公開を行わず却下記録を出力して終了する。"""
    reason = str(ctx.state.get("human_review") or _extract_text(node_input) or "却下")
    summary = (
        "# 🛑 コンテンツ公開中止\n\n"
        f"- ステータス: 却下（未公開）\n"
        f"- 判断内容: {reason}\n"
        "- 対応: 原稿を修正のうえ再度コンプライアンス審査を実施してください。"
    )
    yield Event(
        author="rejection_notifier",
        content=types.Content(role="model", parts=[types.Part.from_text(text=summary)]),
    )
    yield Event(output=summary)


# =====================================================
# Human-in-the-Loop ワークフロー定義（Workflow + Resumable App）
# =====================================================
root_agent = Workflow(
    name="content_approval_workflow",
    description="コンプライアンス審査結果に応じて人間承認ゲートを挟む公開承認ワークフロー",
    edges=[
        (
            "START",
            content_creator,
            compliance_checker,
            compliance_router,
            {
                "AUTO_APPROVED": final_publisher,
                "HUMAN_REVIEW_REQUIRED": human_review_gate,
            },
        ),
        (
            human_review_gate,
            {
                "APPROVED": final_publisher,
                "REJECTED": rejection_notifier,
            },
        ),
    ],
)

with warnings.catch_warnings():
    warnings.simplefilter("ignore", UserWarning)
    app = App(
        name="content_approval_app",
        root_agent=root_agent,
        resumability_config=ResumabilityConfig(is_resumable=True),
    )
