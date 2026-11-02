"""Swarm Pattern - 製品設計コンセンサスエージェント（Workflow 版）。

ADK v2 Workflow API を使用。
市場・技術・財務の 3 名の専門家エージェントとファシリテーター（`consensus_builder`）が議論し、
決定論的ルーター `@node`（`consensus_router`）が合意到達または最大ラウンド数（`MAX_ROUNDS`）まで
サイクルを回す。

実装アプローチ:
    1. `market_expert` が初回はユーザー要求から初期案を作成し、2 ラウンド目以降は前ラウンドの
       `consensus_document` に残された未解決論点を踏まえて改訂提案を作成する。
    2. `engineer_expert` → `finance_expert` → `consensus_builder` が順に多角的な評価・統合を行う。
    3. `consensus_router`（`@node`）が `[CONSENSUS_REACHED]` / `[NEEDS_ANOTHER_ROUND]` と
       ラウンド上限を検査し、`REVISE` ルートで次ラウンドへ戻すか完了させる。
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

MAX_ROUNDS = 3


def _extract_text(value: Any) -> str:
    """ノード入力からプレーンテキストを抽出する。"""
    if isinstance(value, str):
        return value
    if isinstance(value, types.Content) and value.parts:
        return "".join(
            p.text for p in value.parts if p.text and not getattr(p, "thought", False)
        )
    return str(value or "")


async def _build_market_expert_instruction(ctx: ReadonlyContext) -> str:
    """初回は新規市場提案、2 ラウンド目以降は前ラウンドの未解決課題に対する改訂提案を指示する。"""
    prev_consensus = ctx.state.get("consensus_document", "")
    round_num = int(ctx.state.get("swarm_round", 0)) + 1

    prior_section = ""
    if prev_consensus:
        prior_section = f"""
## 前ラウンド（Round {round_num - 1}）の統合ドキュメントと未解決課題
以下の未解決論点を解消するよう、市場・顧客視点からスコープや優先順位を調整した改訂案を提示してください:

{prev_consensus}
"""

    return f"""\
あなたはプロダクトマーケターです（議論 Round {round_num}）。

ユーザーが提示した製品アイデアについて、市場・顧客視点から分析してください:
{prior_section}
1. **ターゲット顧客とペルソナ**: 誰が使うか
2. **市場規模と成長性**: TAM/SAM/SOM の推定
3. **顧客が真に求めるもの**: Jobs to be Done
4. **競合製品との差別化ポイント**
5. **Go-to-Market 戦略の提案**

分析後、製品設計の提案をまとめてください。これが他の専門家との議論の土台になります。
"""


# =====================================================
# 専門家エージェント群
# =====================================================
market_expert = LlmAgent(
    name="market_expert",
    model=settings.default_model,
    description="市場・顧客視点から製品設計を評価・提案する専門家",
    instruction=_build_market_expert_instruction,
    output_key="market_proposal",
)

engineer_expert = LlmAgent(
    name="engineer_expert",
    model=settings.default_model,
    description="技術的実現可能性・アーキテクチャの観点から評価する専門家",
    instruction="""\
あなたはシニアエンジニアです。

## 市場専門家の提案
{market_proposal}

技術的観点から以下を評価・補完してください:
1. 技術的な実現可能性と難易度（1〜10）
2. 推奨するアーキテクチャ・技術スタック
3. 開発工数の見積もり（チーム規模、期間）
4. 技術的リスクと軽減策
5. スケーラビリティの考慮点

市場提案の技術的な妥当性を評価し、修正提案があれば述べてください。
""",
    output_key="engineer_proposal",
)

finance_expert = LlmAgent(
    name="finance_expert",
    model=settings.default_model,
    description="財務・収益性・投資対効果の観点から評価する専門家",
    instruction="""\
あなたは CFO です。

## 市場専門家の提案
{market_proposal}

## エンジニアの提案
{engineer_proposal}

財務・ビジネス観点から以下を評価してください:
1. 初期投資とランニングコストの試算
2. 収益モデルと ROI 予測（12ヶ月、36ヶ月）
3. 優先すべき機能（コスト対効果が高いもの）
4. フェーズ分けの提案（MVP → v1 → v2）

## コンセンサス評価
3者の意見を踏まえ、以下を判断してください:
- 合意できる点
- まだ議論が必要な点

コンセンサスレベルが 70% 以上なら `[SWARM_CONSENSUS]` と記載してください。
""",
    output_key="finance_proposal",
)

# =====================================================
# 最終コンセンサスドキュメント作成エージェント
# =====================================================
consensus_builder = LlmAgent(
    name="consensus_builder",
    model=settings.default_model,
    description="専門家の議論を整理してコンセンサスドキュメントを作成する",
    instruction="""\
あなたはファシリテーターです。

## 市場専門家の提案
{market_proposal}

## エンジニアの提案
{engineer_proposal}

## 財務専門家の提案
{finance_proposal}

3名の専門家の議論を統合して最終的な製品設計提案書を作成してください:

# 製品設計コンセンサスドキュメント

## 合意した製品コンセプト
## 技術アーキテクチャ（合意版）
## ビジネスモデル（合意版）
## 実装フェーズ計画
## 未解決の課題（次のステップ）

## 最終判定
- 3者の合意が十分に成立している場合は必ず `[CONSENSUS_REACHED]` と記載してください。
- 重大な対立や未解決論点が残り再議論が必要な場合は必ず `[NEEDS_ANOTHER_ROUND]` と記載してください。
""",
    output_key="consensus_document",
)


# =====================================================
# 決定論的コンセンサスルーター（@node）
# =====================================================
@node(name="consensus_router")
def consensus_router(ctx: Context, node_input: Any) -> Event:
    """合意判定タグと最大ラウンド数（`MAX_ROUNDS`）を検査し、再議論または合意完了へ分岐する。"""
    round_num = int(ctx.state.get("swarm_round", 0)) + 1
    doc = _extract_text(node_input) or str(ctx.state.get("consensus_document", ""))
    upper = doc.upper()

    consensus_reached = "[CONSENSUS_REACHED]" in upper
    needs_more = (
        "[NEEDS_ANOTHER_ROUND]" in upper
        or "REVISE" in upper
        or "NEXT_ROUND" in upper
    ) and not consensus_reached

    if needs_more and round_num < MAX_ROUNDS:
        return Event(
            output=doc,
            route="REVISE",
            state={"swarm_round": round_num, "consensus_document": doc},
        )
    return Event(
        output=doc,
        route="CONSENSUS",
        state={"swarm_round": round_num, "consensus_document": doc},
    )


@node(name="finalize_consensus")
def finalize_consensus(ctx: Context, node_input: Any) -> str:
    """最終合意ドキュメントをワークフロー出力として返す。"""
    return str(ctx.state.get("consensus_document") or _extract_text(node_input))


# =====================================================
# Swarm: Workflow による条件付きサイクル + ラウンド上限ガード
# =====================================================
root_agent = Workflow(
    name="product_design_swarm",
    description="複数の専門家エージェントが議論してコンセンサスで製品設計を決定するスウォームシステム",
    edges=[
        (
            "START",
            market_expert,
            engineer_expert,
            finance_expert,
            consensus_builder,
            consensus_router,
            {"REVISE": market_expert, "CONSENSUS": finalize_consensus},
        ),
    ],
)
