"""Capstone: Enterprise Research Agent - 全デザインパターン統合（Workflow 版）。

ADK v2 Workflow API を使用。
旧 SequentialAgent / ParallelAgent / LoopAgent を Workflow に移行。

このエージェントは、学んだ全パターンを組み合わせて
「企業の技術戦略評価レポート」を自動生成する。

## 使用するパターン

1. Coordinator (Lv.8):  ユーザーリクエストを専門チームに振り分ける
2. Parallel:            複数ソースから同時並行でデータ収集（ネストタプル）
3. Sequential:          データ収集 → 分析 → レポート生成の順次処理（チェーンタプル）
4. Loop:                品質が基準に達するまでレポートを改善（条件付きサイクル）
5. Review & Critique:   最終レポートを厳格に評価

## データ受け渡し方法

並列ノード（ネストタプル）の output_key で state_delta に書き込まれたデータは、
セッション状態（session.state）へのマージタイミングが保証されない。
そのため、fan-in 先のノード（analysis_agent, report_writer, report_critic）では
instruction を **callable (async function)** にし、ReadonlyContext.state.get() で
安全にデータを取得する。これにより KeyError を回避できる。

## アーキテクチャ図

```
User Request
    │
    ▼
[Workflow: root_agent]
    │
    ├── [Coordinator]                        ← ユーザーの意図を解釈
    │
    ├── [Parallel: (web, tech, financial)]  → 各 *_data
    │
    ├── [analysis_agent]                    → analysis_result  (callable instruction)
    │
    ├── [report_writer]                     → report_draft     (callable instruction)
    │
    └── [report_critic]                     → critic_feedback  (callable instruction)
          ↺ NEEDS_IMPROVEMENT → report_writer（条件付きサイクル）
```
"""

import sys
from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.workflow import Workflow

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.config import get_settings

settings = get_settings()

# =====================================================
# Layer: データ収集（Parallel）
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

# =====================================================
# Layer: 統合分析（Sequential の中間ステップ）
#   ※ 並列ノード（ネストタプル）の直後に実行される fan-in ノードのため、
#     instruction を callable にして ReadonlyContext.state.get() で
#     安全にデータを取得する（state_delta のマージタイミング問題を回避）。
# =====================================================


async def _build_analysis_instruction(ctx: ReadonlyContext) -> str:
    """analysis_agent 用の instruction を動的に構築する。

    並列ノードの state_delta がセッションに反映された後に
    ReadonlyContext.state から安全にデータを取得する。
    """
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

## 分析を行ってください

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
- リスクスコア (1-10 、低いほど良い)

分析結果を構造化されたテキストで出力してください。
"""


analysis_agent = LlmAgent(
    name="enterprise_analyst",
    model=settings.default_model,
    description="収集したデータを統合して戦略的分析を行う",
    instruction=_build_analysis_instruction,  # callable: 並列ノードの state_delta 反映後に評価
    output_key="analysis_result",
)

# =====================================================
# Layer: レポート生成 + レビュー（条件付きサイクル）
#   ※ report_writer: 並列ノード由来の変数 (web_data 等) を参照するため callable。
#   ※ report_critic: 条件付きサイクルで再実行されるため callable で安全に取得。
# =====================================================


async def _build_report_writer_instruction(ctx: ReadonlyContext) -> str:
    """report_writer 用の instruction を動的に構築する。

    analysis_result は Sequential の前ステップから取得（順序保証あり）。
    web_data / tech_data / financial_data は並列ノード由来のため、
    state.get() で安全にフォールバック付きで取得する。
    """
    analysis_result = ctx.state.get("analysis_result", "（データなし）")
    web_data = ctx.state.get("web_data", "（データなし）")
    tech_data = ctx.state.get("tech_data", "（データなし）")
    financial_data = ctx.state.get("financial_data", "（データなし）")
    return f"""\
あなたはビジネスライターです。

## 分析データ
{analysis_result}

## 生データ（参考）
企業情報: {web_data}
技術情報: {tech_data}
財務情報: {financial_data}

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
    """report_critic 用の instruction を動的に構築する。

    report_draft は Sequential の前ステップ (report_writer) から取得。
    条件付きサイクルで再実行される場合にも安全にデータを取得する。
    """
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
スコア 85 以上: [REPORT_APPROVED] - 配布可能
スコア 85 未満: NEEDS_IMPROVEMENT - 改善して再提出
"""


report_writer = LlmAgent(
    name="enterprise_report_writer",
    model=settings.default_model,
    description="分析データからエグゼクティブレポートを生成・改善する",
    instruction=_build_report_writer_instruction,  # callable: 並列ノード由来の変数を安全に取得
    output_key="report_draft",
)

report_critic = LlmAgent(
    name="enterprise_report_critic",
    model=settings.default_model,
    description="レポートの品質を厳格に評価してフィードバックを提供する",
    instruction=_build_report_critic_instruction,  # callable: サイクル再実行時にも安全に取得
    output_key="critic_feedback",
)

# =====================================================
# メインパイプライン + Coordinator 統合（Workflow）
#   ※ Workflow は BaseAgent ではないため sub_agents に入れられない。
#   ※ 代わりに coordinator を Workflow edges の最初のノードとして組み込む。
#
#   1. Coordinator（ユーザーリクエスト解釈）
#   2. 並列データ収集（ネストタプル）
#   3. 統合分析
#   4. レポート生成 → 評価（条件付きサイクル）
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

root_agent = Workflow(
    name="enterprise_research_workflow",
    description="全デザインパターン統合: Coordinator + Parallel + Sequential + Loop + Review",
    edges=[
        (
            "START",
            coordinator,
            (web_researcher, tech_researcher, financial_researcher),
            analysis_agent,
            report_writer,
            report_critic,
            {"NEEDS_IMPROVEMENT": report_writer},
        ),
    ],
)
