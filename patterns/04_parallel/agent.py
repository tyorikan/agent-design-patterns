"""Parallel Pattern - マルチソース AI ニュース集約エージェント（Workflow v2）。

ADK v2 の Workflow ネストタプルで Parallel fan-out/fan-in を実現。
('START', (a, b, c, d), aggregator) で並列 → 集約を表現する。

⚠️ v2 Workflow のデータ受け渡し:
  並列ノード（ネストタプル）の output_key は state_delta 経由で
  セッション状態に書き込まれるが、fan-in ノードの instruction が
  評価される時点でマージが保証されない場合がある。
  → fan-in ノードの instruction は **callable** にして
    ReadonlyContext.state から安全に参照する。

データフロー（並列）:
    ┌→ [Google AI Researcher]  output_key="google_ai_news"   →┐
    ├→ [OpenAI Researcher]     output_key="openai_news"      →├→ [Synthesizer]
    ├→ [Regulation Researcher] output_key="regulation_news"  →┘
    └→ [Industry Researcher]   output_key="industry_news"
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
# 並列実行するリサーチエージェント群
# ⚠️ 各エージェントは必ず異なる output_key を使う！
# ⚠️ 最初から実行されるので instruction に {変数} は使わない
# =====================================================

google_ai_researcher = LlmAgent(
    name="google_ai_researcher",
    model=settings.default_model,
    description="Google の AI/Gemini の最新動向を調査する",
    instruction="""\
あなたは Google AI のリサーチャーです。
ユーザーが調査を依頼したトピックに関連した、Google の AI（Gemini、Vertex AI、DeepMind）
の最新動向を簡潔にまとめてください。

調査内容:
- 最新モデルのリリースと性能
- Google Cloud AI サービスの新機能
- 研究論文や技術的なブレークスルー
- Google の AI 戦略と投資動向

主要なアップデートを3〜5件、各1〜2文で箇条書きにしてください。
""",
    output_key="google_ai_news",  # 固有のキー（他と重複禁止）
)

openai_researcher = LlmAgent(
    name="openai_researcher",
    model=settings.default_model,
    description="OpenAI/ChatGPT 周辺の最新動向を調査する",
    instruction="""\
あなたは AI 業界のリサーチャーです。
ユーザーが調査を依頼したトピックに関連した、OpenAI や ChatGPT の最新動向を
簡潔にまとめてください。

調査内容:
- 最新モデル（GPT-4o、o1 など）のアップデート
- ChatGPT の新機能
- API の変更・新機能
- OpenAI の戦略・パートナーシップ

主要なアップデートを3〜5件、各1〜2文で箇条書きにしてください。
""",
    output_key="openai_news",  # 固有のキー
)

regulation_researcher = LlmAgent(
    name="regulation_researcher",
    model=settings.default_model,
    description="AI 規制・政策動向を調査する",
    instruction="""\
あなたは AI 規制の専門家です。
ユーザーが調査を依頼したトピックに関連した AI の規制・政策・倫理の
最新動向を簡潔にまとめてください。

調査内容:
- EU AI Act などの法規制の進捗
- 各国政府の AI 戦略・ガイドライン
- 業界団体の自主規制の動向
- AI の倫理・安全性に関する主要な議論

主要な動向を3〜5件、各1〜2文で箇条書きにしてください。
""",
    output_key="regulation_news",  # 固有のキー
)

industry_researcher = LlmAgent(
    name="industry_researcher",
    model=settings.default_model,
    description="AI の産業応用事例を調査する",
    instruction="""\
あなたは産業アナリストです。
ユーザーが調査を依頼したトピックに関連した AI の具体的な産業応用事例の
最新動向を簡潔にまとめてください。

調査内容:
- 医療・ヘルスケアでの AI 活用
- 製造・物流での AI 活用
- 金融・フィンテックでの AI 活用
- 小売・eコマースでの AI 活用

各産業から事例を1件ずつ、合計3〜5件を箇条書きにしてください。
""",
    output_key="industry_news",  # 固有のキー
)


# =====================================================
# 集約エージェント（並列結果をまとめる）
# ★ v2 Workflow: ネストタプルの fan-in ノードでは
#   instruction を callable にして ReadonlyContext.state から
#   並列ノードの output_key を安全に参照する
# =====================================================
async def _build_synthesizer_instruction(ctx: ReadonlyContext) -> str:
    """並列ノードの output_key を ReadonlyContext.state から安全に取得。"""
    google_ai = ctx.state.get("google_ai_news", "（データなし）")
    openai_news = ctx.state.get("openai_news", "（データなし）")
    regulation = ctx.state.get("regulation_news", "（データなし）")
    industry = ctx.state.get("industry_news", "（データなし）")

    return f"""\
以下の4つのリサーチ結果を統合して、包括的なトレンドレポートを作成してください。

## 収集したデータ

### Google AI の動向
{google_ai}

### OpenAI の動向
{openai_news}

### 規制・政策の動向
{regulation}

### 産業応用の動向
{industry}

---

## 作成するレポートの構成

# AI 最新動向レポート

## エグゼクティブサマリー
（全体を通じた最重要トレンドを3点）

## テクノロジー競争の状況
（Google vs OpenAI の比較と分析）

## 規制環境の整理
（企業が注意すべき規制動向）

## ビジネスチャンス
（産業応用から見える機会）

## まとめと予測
"""


synthesizer = LlmAgent(
    name="synthesizer",
    model=settings.default_model,
    description="並列収集した情報を統合してレポートを作成する",
    instruction=_build_synthesizer_instruction,  # callable で安全に state 参照
)

# =====================================================
# Workflow ネストタプルで Parallel fan-out/fan-in を実現
# ('START', (a, b, c, d), synthesizer)
#   → 4エージェント並列実行 → synthesizer で集約
# =====================================================
root_agent = Workflow(
    name="news_aggregator",
    description="複数ソースを並列調査して統合レポートを作成するニュース集約システム",
    edges=[
        (
            "START",
            # fan-out: 4エージェントを並列実行（レイテンシ削減）
            (
                google_ai_researcher,
                openai_researcher,
                regulation_researcher,
                industry_researcher,
            ),
            # fan-in: 全並列結果を集約
            synthesizer,
        ),
    ],
)
