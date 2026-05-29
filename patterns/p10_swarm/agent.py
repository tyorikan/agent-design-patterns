"""Swarm Pattern - 製品設計コンセンサスエージェント（Workflow 版）。

ADK v2 Workflow API を使用。
旧 LoopAgent + SequentialAgent を Workflow の条件付きサイクルに移行。

ADK の {変数名} の注意:
    - Workflow の最初のイテレーション開始時、セッション状態が空
    - market_expert（最初に実行）は {design_proposal} を参照できない
    - 最初のエージェントはユーザーメッセージから直接読み取る

実装アプローチ:
    market_expert が最初に動き、提案を整理し market_proposal に保存。
    以降のエージェントは {market_proposal} を参照しながら議論を深める。
    finance_expert がコンセンサスレベルを判定し、未達なら REVISE で再議論。
"""

import sys
from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.workflow import Workflow

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.config import get_settings

settings = get_settings()

# =====================================================
# 専門家エージェント
# market_expert が最初: {変数} を使わない
# =====================================================

market_expert = LlmAgent(
    name="market_expert",
    model=settings.default_model,
    description="市場・顧客視点から製品設計を評価・提案する専門家",
    instruction="""\
あなたはプロダクトマーケターです。

ユーザーが提示した製品アイデアについて、市場・顧客視点から分析してください:

1. **ターゲット顧客とペルソナ**: 誰が使うか
2. **市場規模と成長性**: TAM/SAM/SOM の推定
3. **顧客が真に求めるもの**: Jobs to be Done
4. **競合製品との差別化ポイント**
5. **Go-to-Market 戦略の提案**

分析後、製品設計の初期提案をまとめてください。
これが他の専門家との議論の出発点になります。
""",
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

コンセンサスレベルが70%以上なら [SWARM_CONSENSUS] と記載してください。
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
コンセンサスが十分に取れていない場合は REVISE と記載してください。
コンセンサスが取れた場合はそのまま提案書を完成させてください。
""",
    output_key="market_proposal",  # 次のループサイクルへのフィードバック
)

# =====================================================
# Swarm: Workflow による条件付きサイクル
#   market → engineer → finance → consensus_builder
#   consensus_builder が REVISE を返したら market_expert に戻る
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
            {"REVISE": market_expert},
        ),
    ],
)
