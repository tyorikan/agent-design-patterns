"""Capstone: Enterprise Research Agent - 全デザインパターン統合（Workflow 版）。

ADK v2 Workflow API を使用し、以下のデザインパターンを単一パイプラインに統合して
「企業の技術戦略評価レポート」を自動生成する。

## 統合しているデザインパターン

1. Coordinator:       ユーザー要求から分析対象企業と調査スコープを構造化
2. Parallel + Join:   3 専門リサーチャーの並列収集と `JoinNode` によるバリア同期（重複実行防止）
3. Sequential:        データ収集 → 統合戦略分析 → レポート執筆の直列パイプライン
4. Review & Critique: 執筆者（`report_writer`）と品質審査官（`report_critic`）の分離
5. Loop (@node 制御): `report_review_router` がスコア判定と最大反復回数（`MAX_REVIEW_ITERATIONS`）を制御
"""

import sys
from pathlib import Path
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.agents.context import Context
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.events.event import Event
from google.adk.workflow import JoinNode, Workflow, node
from google.genai import types

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.config import get_settings

settings = get_settings()

MAX_REVIEW_ITERATIONS = 3


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
# Layer 1: Coordinator（調査スコープ明確化）
# =====================================================
coordinator = LlmAgent(
    name="enterprise_research_coordinator",
    model=settings.default_model,
    description="エンタープライズリサーチのコーディネーター。",
    instruction="""\
あなたは企業分析プロジェクトのディレクターです。

ユーザーからの分析依頼を受け取り、分析対象企業を特定してください。
ユーザーのリクエストを明確化し、企業名と分析の観点を整理して出力してください。
""",
    output_key="coordinator_output",
)

# =====================================================
# Layer 2: データ収集（Parallel Fan-out + JoinNode Fan-in）
# =====================================================
web_researcher = LlmAgent(
    name="enterprise_web_researcher",
    model=settings.default_model,
    description="企業の公式情報・プレスリリース・製品情報を収集する",
    instruction="""\
あなたは企業リサーチの専門家です。

ユーザーが分析対象として指定した企業について、
以下の観点で情報を収集・整理してください:

1. **企業基本情報**
   - 設立年、本社所在地、従業員数
   - 主要事業と収益規模
   - ミッション・ビジョン・バリュー

2. **技術・製品ポートフォリオ**
   - 主要製品/サービスとその市場ポジション
   - 最新の製品リリース・アップデート
   - 技術的な強み・弱み

3. **最新動向**
   - 直近の主要ニュース（M&A、提携、新製品など）
   - 経営陣の変更
   - 戦略的な方向性

調査結果を箇条書きで、各カテゴリごとに整理してください。
""",
    output_key="web_data",
)

tech_researcher = LlmAgent(
    name="enterprise_tech_researcher",
    model=settings.default_model,
    description="企業の技術スタック・エンジニアリング文化・オープンソース活動を調査する",
    instruction="""\
あなたは技術調査の専門家です。

ユーザーが分析対象として指定した企業の技術力について、
以下の観点で調査してください:

1. **技術スタック**
   - 使用している主要プログラミング言語・フレームワーク
   - クラウド・インフラの選択
   - データベース・データ基盤の構成

2. **エンジニアリング文化**
   - エンジニアの評判（求人、口コミ）
   - 技術ブログ・カンファレンス登壇の状況
   - DevOps・開発プロセスの成熟度

3. **AI/ML への取り組み**
   - AI/ML の採用状況と活用例
   - 生成 AI・LLM への投資・活用
   - データ戦略の方向性

4. **オープンソース**
   - GitHub での活動状況（スター数、コントリビューター）
   - 主要 OSS の公開状況

技術的な観点から企業の競争力を評価してください。
""",
    output_key="tech_data",
)

financial_researcher = LlmAgent(
    name="enterprise_financial_researcher",
    model=settings.default_model,
    description="企業の財務パフォーマンス・成長性・投資家動向を調査する",
    instruction="""\
あなたは財務調査の専門家です。

ユーザーが分析対象として指定した企業の財務状況について、
以下の観点で調査してください:

1. **財務パフォーマンス**
   - 売上高・成長率（YoY）
   - 利益率（粗利、営業利益、純利益）
   - キャッシュフロー状況

2. **投資動向**
   - R&D 投資額と投資率
   - M&A・投資活動
   - 設備投資の方向性

3. **市場評価**
   - 時価総額（上場企業の場合）
   - PER・PSR などのバリュエーション
   - アナリスト評価

4. **リスク要因**
   - 財務的なリスク
   - 規制・法的リスク
   - 市場リスク

財務的な観点から企業の健全性と成長ポテンシャルを評価してください。
""",
    output_key="financial_data",
)

# 3 リサーチャー全ての完了を待機するバリア同期ノード（後続ノードの 3 重実行を防止）
join_research = JoinNode(name="join_enterprise_research")


# =====================================================
# Layer 3: 統合分析（Sequential 中間ステップ）
# =====================================================
async def _build_analysis_instruction(ctx: ReadonlyContext) -> str:
    """並列収集された 3 領域のデータを安全に取得して戦略分析プロンプトを構築する。"""
    web_data = ctx.state.get("web_data", "（データなし）")
    tech_data = ctx.state.get("tech_data", "（データなし）")
    financial_data = ctx.state.get("financial_data", "（データなし）")
    return f"""\
あなたは戦略コンサルタントです。
以下の収集データを統合して、包括的な戦略分析を行ってください。

## 収集データ

### 企業基本情報・動向
{web_data}

### 技術力・エンジニアリング
{tech_data}

### 財務状況
{financial_data}

---

## 分析項目

### 1. SWOT 分析
- **強み (Strengths)**: 内部の競争優位性（技術、ブランド、財務など）
- **弱み (Weaknesses)**: 内部の改善が必要な点
- **機会 (Opportunities)**: 外部環境からのビジネスチャンス
- **脅威 (Threats)**: 外部からのリスク・競合の動き

### 2. 技術戦略の評価
- AI/デジタル変革への対応状況
- 技術的負債とイノベーションのバランス
- エンジニアリング組織の成熟度スコア (1-10)

### 3. 競合ポジショニング
- 主要競合との差別化ポイント
- 市場シェアの動向予測
- 競争優位性の持続可能性

### 4. 投資家目線での評価
- 成長性スコア (1-10)
- 収益性スコア (1-10)
- リスクスコア (1-10、低いほど良い)

分析結果を構造化されたテキストで出力してください。
"""


analysis_agent = LlmAgent(
    name="enterprise_analyst",
    model=settings.default_model,
    description="収集したデータを統合して戦略的分析を行う",
    instruction=_build_analysis_instruction,
    output_key="analysis_result",
)


# =====================================================
# Layer 4: レポート執筆 + 品質批評ループ（Review & Critique + @node Loop）
# =====================================================
async def _build_report_writer_instruction(ctx: ReadonlyContext) -> str:
    """初回は新規レポート作成、再試行時は `critic_feedback` を反映した改訂を行う。"""
    analysis_result = ctx.state.get("analysis_result", "（データなし）")
    web_data = ctx.state.get("web_data", "（データなし）")
    tech_data = ctx.state.get("tech_data", "（データなし）")
    financial_data = ctx.state.get("financial_data", "（データなし）")
    prev_draft = ctx.state.get("report_draft", "")
    feedback = ctx.state.get("critic_feedback", "")

    revision_section = ""
    if feedback:
        revision_section = f"""
## 前回のレポートドラフト
{prev_draft}

## 品質審査官からの改善指示（すべて反映して改稿してください）
{feedback}
"""

    return f"""\
あなたはビジネスライターです。

## 分析データ
{analysis_result}

## 生データ（参考）
企業情報: {web_data}
技術情報: {tech_data}
財務情報: {financial_data}
{revision_section}
---

以下の形式でエグゼクティブレポートを作成してください:

---
# 企業技術戦略評価レポート

## エグゼクティブサマリー
（最重要な発見と推奨事項を3〜5点）

## 企業概要
（事業内容・規模・市場ポジション）

## 技術戦略の評価
（技術力・AI/ML・エンジニアリング組織の評価）

## 財務健全性
（成長性・収益性・投資活動）

## SWOT 分析
（4象限の要点）

## リスクと機会
（主要リスクと対処法、ビジネスチャンス）

## 推奨アクション
（自社がこの企業と関わる場合のアクション提案3点）

## 総合評価
- 総合スコア: X/100
- 投資魅力度: ★★★☆☆
- 技術パートナーとしての魅力: ★★★★☆
---
"""


async def _build_report_critic_instruction(ctx: ReadonlyContext) -> str:
    """`report_draft` を安全に取得して厳格な品質評価を行う。"""
    report_draft = ctx.state.get("report_draft", "（レポートなし）")
    return f"""\
あなたは品質管理の専門家です。
以下のエグゼクティブレポートを厳格に評価してください。

## 評価対象レポート
{report_draft}

## 評価基準

1. **正確性** (25点): データに基づいた正確な記述か
2. **完全性** (25点): 必要なセクションが全て含まれているか
3. **明瞭性** (25点): 意思決定者が理解・活用できる内容か
4. **実用性** (25点): 具体的な推奨アクションが含まれているか

## 評価結果

### スコア
- 総合スコア: XX/100

### 優れている点
（3点以内）

### 改善が必要な点
（3点以内、具体的に）

### 最終判定
- スコア 85 以上なら必ず `[REPORT_APPROVED]` - 配布可能 と記載してください
- スコア 85 未満なら必ず `[NEEDS_IMPROVEMENT]` - 改善して再提出 と記載してください
"""


report_writer = LlmAgent(
    name="enterprise_report_writer",
    model=settings.default_model,
    description="分析データからエグゼクティブレポートを生成・改善する",
    instruction=_build_report_writer_instruction,
    output_key="report_draft",
)

report_critic = LlmAgent(
    name="enterprise_report_critic",
    model=settings.default_model,
    description="レポートの品質を厳格に評価してフィードバックを提供する",
    instruction=_build_report_critic_instruction,
    output_key="critic_feedback",
)


@node(name="report_review_router")
def report_review_router(ctx: Context, node_input: Any) -> Event:
    """批評結果と反復回数上限（`MAX_REVIEW_ITERATIONS`）を検査して分岐する。"""
    iteration = int(ctx.state.get("capstone_review_iteration", 0)) + 1
    feedback = _extract_text(node_input) or str(ctx.state.get("critic_feedback", ""))
    upper = feedback.upper()

    is_approved = "[REPORT_APPROVED]" in upper
    needs_improvement = (
        "NEEDS_IMPROVEMENT" in upper or "REVISE" in upper
    ) and not is_approved

    if needs_improvement and iteration < MAX_REVIEW_ITERATIONS:
        return Event(
            output=feedback,
            route="NEEDS_IMPROVEMENT",
            state={
                "capstone_review_iteration": iteration,
                "critic_feedback": feedback,
            },
        )
    return Event(
        output=str(ctx.state.get("report_draft", feedback)),
        route="APPROVED",
        state={
            "capstone_review_iteration": iteration,
            "critic_feedback": feedback,
        },
    )


@node(name="finalize_enterprise_report")
def finalize_enterprise_report(ctx: Context, node_input: Any) -> str:
    """承認済み（または上限到達時）のエグゼクティブレポートを返す。"""
    return str(ctx.state.get("report_draft") or _extract_text(node_input))


# =====================================================
# メインパイプライン（Workflow 全構文統合）
# =====================================================
root_agent = Workflow(
    name="enterprise_research_workflow",
    description="全デザインパターン統合: Coordinator + Parallel(JoinNode) + Sequential + Loop + Review",
    edges=[
        (
            "START",
            coordinator,
            (web_researcher, tech_researcher, financial_researcher),
            join_research,
            analysis_agent,
            report_writer,
            report_critic,
            report_review_router,
            {
                "NEEDS_IMPROVEMENT": report_writer,
                "APPROVED": finalize_enterprise_report,
            },
        ),
    ],
)
