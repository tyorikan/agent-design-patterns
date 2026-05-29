"""Single Agent パターン - GCP ドキュメント Q&A エージェント。

パターンの特徴:
    1 つの LlmAgent が tools を使いながら自律的にタスクを完了する。
    最もシンプルなパターン。ここから始めよう。
"""

from google.adk.agents import LlmAgent
from google.adk.tools import google_search

from shared.config import get_settings

settings = get_settings()


def get_current_date() -> dict[str, str]:
    """現在の日付を取得します。

    Returns:
        現在の日付情報を含む辞書
    """
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    return {
        "date": now.strftime("%Y-%m-%d"),
        "year": str(now.year),
        "note": "この情報は検索結果の日付判断に使用してください",
    }


# =====================================================
# Single Agent の定義
# =====================================================
# LlmAgent = 「LLM が自律的に考えてツールを選択・実行するエージェント」
#
# 重要なパラメータ:
#   name        : エージェントの一意な識別子
#   model       : 使用する Gemini モデル
#   description : 他エージェントがこのエージェントを参照する際の説明
#   instruction : システムプロンプト（エージェントの振る舞いを定義）
#   tools       : 使用可能なツールのリスト
# =====================================================
root_agent = LlmAgent(
    name="gcp_docs_agent",
    model=settings.default_model,
    description="Google Cloud のドキュメントや最新情報を検索して回答する専門エージェント",
    instruction="""
あなたは Google Cloud のエキスパートエンジニアです。
ユーザーの Google Cloud に関する質問に、正確かつ実用的に回答してください。

## 行動指針
1. **最新情報を確認**: 常に google_search で最新のドキュメントを参照してください
2. **実用的な回答**: コード例や具体的な手順を含めて回答してください
3. **制約の明示**: もし情報が不確かな場合は、その旨を明示してください
4. **日本語で回答**: ユーザーへの回答は日本語で行ってください

## ツールの使い方
- `google_search`: "site:cloud.google.com" を付けると公式ドキュメントを優先的に検索できます
- `get_current_date`: 情報の鮮度を確認する際に使用してください

## 回答フォーマット
- 概要（1〜2文）
- 詳細説明
- 具体的な手順やコード例（必要な場合）
- 公式ドキュメントへのリンク
""",
    tools=[
        google_search,
        get_current_date,
    ],
)
