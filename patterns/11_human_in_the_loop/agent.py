"""Human-in-the-Loop Pattern - コンテンツ承認ワークフロー。

パターンの特徴:
    エージェントが処理を一時停止し、人間の判断を待つパターン。
    高リスクな操作や主観的な判断が必要な場合に使用する。

    実装アプローチ:
    ADK では ToolContext.actions.escalate を使うことで
    LoopAgent の反復を終了させ、人間の入力を求めることができる。
    ここではコンソール入力を使って人間の承認をシミュレートする。
"""

import sys
from pathlib import Path

from google.adk.agents import LlmAgent

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.config import get_settings

settings = get_settings()

# =====================================================
# コンテンツ生成エージェント
# =====================================================
content_creator = LlmAgent(
    name="content_creator",
    model=settings.default_model,
    description="マーケティングコンテンツを生成する",
    instruction="""
あなたはマーケティングコピーライターです。
以下のリクエストに基づいてマーケティングコンテンツを生成してください。

## リクエスト
{content_request}

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
# コンプライアンスチェックエージェント
# =====================================================
compliance_checker = LlmAgent(
    name="compliance_checker",
    model=settings.default_model,
    description="コンテンツのコンプライアンスチェックを行う",
    instruction="""
あなたはコンプライアンスオフィサーです。
以下のマーケティングコンテンツを審査してください。

## 審査対象コンテンツ
{generated_content}

## 元のリクエスト
{content_request}

## 審査項目
1. **法的リスク**: 景品表示法、薬機法など法令違反の可能性
2. **誇大表現**: 根拠のない最上級表現（「最高」「唯一」など）
3. **差別・偏見**: 特定グループへの差別的表現
4. **プライバシー**: 個人情報・機密情報の漏洩リスク
5. **競合への言及**: 不適切な競合比較

## 判定結果

### 審査スコア: XX/100

### リスク項目
（問題がある場合は具体的に記述）

### 承認ステータス
- スコア 85 以上かつ高リスク項目なし → **[AUTO_APPROVED]** 自動承認
- スコア 70〜84 または中リスク → **[HUMAN_REVIEW_REQUIRED]** 人間レビュー必須
- スコア 70 未満または高リスク → **[REJECTED]** 修正後再審査

### 推奨アクション
""",
    output_key="compliance_result",
)

# =====================================================
# 最終出力エージェント
# =====================================================
final_publisher = LlmAgent(
    name="final_publisher",
    model=settings.default_model,
    description="承認済みコンテンツを最終形式で出力する",
    instruction="""
あなたはコンテンツマネージャーです。
承認済みのコンテンツを最終形式にまとめてください。

## コンテンツ
{generated_content}

## 承認結果
{compliance_result}

## 人間のレビュー結果
{human_review}

最終的に承認されたコンテンツを以下の形式で出力してください:

---
# 📢 公開承認済みコンテンツ

## メタデータ
- 承認日時: （現在日時）
- 承認ステータス: 承認済み
- コンプライアンスチェック: 完了

## 公開コンテンツ
[コンテンツ本文]

## 公開チャンネル推奨
[最適な配信チャンネルの提案]
---
""",
)

# =====================================================
# Human-in-the-Loop ワークフロー
# =====================================================
# このパターンでは demo.py が人間の入力を受け取り、
# セッション状態に追加してエージェントの続きを実行する
# =====================================================
root_agent = content_creator  # デモ用: 最初にコンテンツ生成のみ

# フルワークフロー（demo.py で段階実行）
workflow_agents = {
    "creator": content_creator,
    "compliance": compliance_checker,
    "publisher": final_publisher,
}
