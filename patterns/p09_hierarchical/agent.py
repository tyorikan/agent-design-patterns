"""Hierarchical Task Decomposition Pattern - 競合分析レポート自動生成。

パターンの特徴:
    3 層の `LlmAgent` ツリー（Root → 部門 Coordinator → 専門 Worker）による階層的タスク分解。

⚠️ 動的委譲における状態参照の安全設計:
    `sub_agents` による LLM 委譲では、親エージェントの判断によってワーカーの呼び出し順序が変わったり、
    一部のワーカーが省略されたりする可能性がある。
    そのため、後続エージェントの `instruction` で `{web_research_data}` のような固定文字列テンプレートを
    直接使うと未設定時に `KeyError` が発生する。
    本実装では `ReadonlyContext.state.get(..., "（未取得）")` を用いた callable instruction により、
    委譲順序に依存せず安全に動作する設計としている。
"""

import sys
from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.config import get_settings

settings = get_settings()


# =====================================================
# Layer 3: Worker エージェント
# =====================================================
web_researcher = LlmAgent(
    name="web_researcher",
    model=settings.default_model,
    description="企業の公式情報・製品・戦略を調査して収集する",
    instruction="""
あなたは企業調査のスペシャリストです。
ユーザーが調査対象として指定した企業について、以下の情報を調査してください:
- 会社概要（創業、本社、従業員数、時価総額）
- 主要製品・サービスとその特徴
- 市場シェアと成長率
- ビジネスモデルと収益構造
- 公式の戦略・ロードマップ

調査結果を箇条書きで簡潔にまとめてください。
""",
    output_key="web_research_data",
)


async def _build_news_researcher_instruction(ctx: ReadonlyContext) -> str:
    """基礎調査データが存在すれば参照し、未取得でも安全にニュース調査を行う。"""
    web_data = ctx.state.get("web_research_data", "（基礎調査データ未取得 — ユーザー依頼から直接特定）")
    return f"""
あなたはニュース調査のスペシャリストです。
以下の企業情報を踏まえて、最新ニュースを調査してください:

{web_data}

調査項目:
- 直近6ヶ月の主要ニュース（製品発表、提携、買収など）
- 業界内でのポジショニング変化
- 顧客・パートナーの評判
- 将来の脅威とリスク要因

調査結果を時系列で箇条書きにまとめてください。
"""


news_researcher = LlmAgent(
    name="news_researcher",
    model=settings.default_model,
    description="最新ニュースや業界動向を調査する",
    instruction=_build_news_researcher_instruction,
    output_key="news_research_data",
)


async def _build_financial_analyst_instruction(ctx: ReadonlyContext) -> str:
    """基礎調査データを安全に参照して財務分析を行う。"""
    web_data = ctx.state.get("web_research_data", "（基礎調査データ未取得）")
    return f"""
あなたは財務アナリストです。
以下のデータを基に財務分析を行ってください:

--- 企業情報 ---
{web_data}

分析項目:
- 収益成長率と利益率のトレンド
- 競合他社との財務比較
- 投資・R&D への支出傾向
- 財務的な強み・弱み

分析結果を数値と根拠を含めて記述してください。
"""


financial_analyst = LlmAgent(
    name="financial_analyst",
    model=settings.default_model,
    description="財務パフォーマンスと市場評価を分析する",
    instruction=_build_financial_analyst_instruction,
    output_key="financial_analysis",
)


async def _build_tech_analyst_instruction(ctx: ReadonlyContext) -> str:
    """基礎調査データと最新ニュースを安全に参照して技術力分析を行う。"""
    web_data = ctx.state.get("web_research_data", "（基礎調査データ未取得）")
    news_data = ctx.state.get("news_research_data", "（ニュース調査データ未取得）")
    return f"""
あなたは技術アナリストです。
以下のデータを基に技術力を分析してください:

--- 企業情報 ---
{web_data}

--- 最新ニュース ---
{news_data}

分析項目:
- コア技術と差別化要因
- AI/ML 活用の状況
- エンジニアリング組織の規模と評判
- 特許・研究論文の動向
- 技術的な強み・弱み

技術的な観点から競争優位性を評価してください。
"""


tech_analyst = LlmAgent(
    name="tech_analyst",
    model=settings.default_model,
    description="技術力・イノベーション能力を分析する",
    instruction=_build_tech_analyst_instruction,
    output_key="tech_analysis",
)

# =====================================================
# Layer 2: Coordinator エージェント
# =====================================================
research_coordinator = LlmAgent(
    name="research_coordinator",
    model=settings.default_model,
    description="企業の基礎情報とニュースを調査する Research チームのコーディネーター",
    instruction="""
あなたはリサーチチームのマネージャーです。
ユーザーが依頼した企業の調査をチームに指示してください。

まず web_researcher に公式情報の調査を依頼し、
次に news_researcher に最新ニュースの調査を依頼してください。

調査完了後、簡単なサマリーを作成してください。
""",
    sub_agents=[web_researcher, news_researcher],
)

analysis_coordinator = LlmAgent(
    name="analysis_coordinator",
    model=settings.default_model,
    description="財務・技術の専門分析を担当する Analysis チームのコーディネーター",
    instruction="""
あなたは分析チームのマネージャーです。
収集されたデータを基に詳細分析をチームに指示してください。

financial_analyst に財務分析を、tech_analyst に技術分析を依頼してください。
それぞれの分析が完了したら、統合サマリーを作成してください。
""",
    sub_agents=[financial_analyst, tech_analyst],
)


async def _build_report_coordinator_instruction(ctx: ReadonlyContext) -> str:
    """全ワーカーの収集・分析データを安全に集約して経営層向けレポートを作成する。"""
    web_data = ctx.state.get("web_research_data", "（未取得）")
    news_data = ctx.state.get("news_research_data", "（未取得）")
    fin_data = ctx.state.get("financial_analysis", "（未取得）")
    tech_data = ctx.state.get("tech_analysis", "（未取得）")
    return f"""
あなたは戦略コンサルタントです。
以下の全分析データを統合して、経営層向けの競合分析レポートを作成してください。

## 収集・分析データ

### 基礎調査
{web_data}

### 最新ニュース
{news_data}

### 財務分析
{fin_data}

### 技術分析
{tech_data}

---

## 作成するレポートの構成

# 競合分析レポート

## エグゼクティブサマリー
（最重要な発見を5行以内で）

## 企業プロファイル
（事業概要と市場ポジション）

## 強み・弱み分析（SWOT の S と W）

## 市場機会・脅威（SWOT の O と T）

## 財務・技術力の評価
（数値根拠付き）

## 戦略的示唆
（自社への影響と推奨アクション3点）

## 結論
"""


report_coordinator = LlmAgent(
    name="report_coordinator",
    model=settings.default_model,
    description="全分析結果を統合してエグゼクティブレポートを作成する",
    instruction=_build_report_coordinator_instruction,
)

# =====================================================
# Layer 1: Root エージェント
# =====================================================
root_agent = LlmAgent(
    name="competitive_analysis_root",
    model=settings.default_model,
    description="競合分析の全プロセスを統括するルートエージェント",
    instruction="""
あなたは競合分析プロジェクトの統括ディレクターです。
ユーザーの依頼を受け取り、以下のチームに順番に分析を指示してください:

1. research_coordinator に基礎調査を依頼
2. analysis_coordinator に詳細分析を依頼
3. report_coordinator に最終レポート作成を依頼

分析対象の企業名をユーザーメッセージから特定してください。
""",
    sub_agents=[
        research_coordinator,
        analysis_coordinator,
        report_coordinator,
    ],
)
