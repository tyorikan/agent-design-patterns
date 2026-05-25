"""Hierarchical Task Decomposition Pattern - 競合分析レポート自動生成（修正版）。

ADK の {変数名} の注意:
    - セッション状態に存在しないキーを参照するとエラー
    - Hierarchical では Root → Coordinator → Worker の順に実行されるが、
      最初のエージェント（Web Researcher など）にはセッション状態が空
    - 最初に実行されるエージェントは {変数} を使わずユーザーメッセージから読み取る

フロー:
    root_agent（Coordinator）
        ├── research_coordinator
        │   ├── web_researcher（公式情報調査、ユーザーメッセージから読み取り）
        │   └── news_researcher（ニュース調査、{web_research_data}を参照）
        ├── analysis_coordinator
        │   ├── financial_analyst（{web_research_data}を参照）
        │   └── tech_analyst（{web_research_data},{news_research_data}を参照）
        └── report_coordinator（全データを参照）
"""

import sys
from pathlib import Path

from google.adk.agents import LlmAgent

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

news_researcher = LlmAgent(
    name="news_researcher",
    model=settings.default_model,
    description="最新ニュースや業界動向を調査する",
    instruction="""
あなたはニュース調査のスペシャリストです。
以下の企業情報を踏まえて、最新ニュースを調査してください:

{web_research_data}

調査項目:
- 直近6ヶ月の主要ニュース（製品発表、提携、買収など）
- 業界内でのポジショニング変化
- 顧客・パートナーの評判
- 将来の脅威とリスク要因

調査結果を時系列で箇条書きにまとめてください。
""",
    output_key="news_research_data",
)

financial_analyst = LlmAgent(
    name="financial_analyst",
    model=settings.default_model,
    description="財務パフォーマンスと市場評価を分析する",
    instruction="""
あなたは財務アナリストです。
以下のデータを基に財務分析を行ってください:

--- 企業情報 ---
{web_research_data}

分析項目:
- 収益成長率と利益率のトレンド
- 競合他社との財務比較
- 投資・R&D への支出傾向
- 財務的な強み・弱み

分析結果を数値と根拠を含めて記述してください。
""",
    output_key="financial_analysis",
)

tech_analyst = LlmAgent(
    name="tech_analyst",
    model=settings.default_model,
    description="技術力・イノベーション能力を分析する",
    instruction="""
あなたは技術アナリストです。
以下のデータを基に技術力を分析してください:

--- 企業情報 ---
{web_research_data}

--- 最新ニュース ---
{news_research_data}

分析項目:
- コア技術と差別化要因
- AI/ML 活用の状況
- エンジニアリング組織の規模と評判
- 特許・研究論文の動向
- 技術的な強み・弱み

技術的な観点から競争優位性を評価してください。
""",
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

report_coordinator = LlmAgent(
    name="report_coordinator",
    model=settings.default_model,
    description="全分析結果を統合してエグゼクティブレポートを作成する",
    instruction="""
あなたは戦略コンサルタントです。
以下の全分析データを統合して、経営層向けの競合分析レポートを作成してください。

## 収集・分析データ

### 基礎調査
{web_research_data}

### 最新ニュース
{news_research_data}

### 財務分析
{financial_analysis}

### 技術分析
{tech_analysis}

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
""",
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
ユーザーの依頼を受け取り、以下のチームに分析を指示してください:

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
