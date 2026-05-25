"""Sequential Pattern - ETL データパイプライン（修正版）。

ADK の {変数名} はセッション状態からの参照。
最初のエージェント（extractor）はセッション状態が空なので {変数} は使えない。
最初のエージェントはユーザーメッセージを直接受け取る形にする。
"""

import sys
from pathlib import Path

from google.adk.agents import LlmAgent, SequentialAgent

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.config import get_settings

settings = get_settings()

# =====================================================
# Step 1: データ抽出エージェント
# ⚠️ 最初のエージェントはセッション状態が空なので
#    {変数名} を使わない。ユーザーメッセージから直接読む。
# =====================================================
extractor_agent = LlmAgent(
    name="extractor",
    model=settings.default_model,
    description="ユーザーが提供した生データを抽出・パースする",
    instruction="""
あなたはデータエクストラクションの専門家です。

ユーザーが提供した生データを分析し、構造化されたデータとして抽出してください。

抽出結果を以下の形式でまとめてください:
- データの種類
- カラム名と各カラムのデータ型
- レコード数
- 主要なデータの内容（最初の3件）
- 特記事項（欠損値、異常値など）

結果は明確なテキスト形式で出力してください。
""",
    output_key="extracted_data",  # セッション状態に "extracted_data" として保存
)

# =====================================================
# Step 2: データ検証エージェント
# ★ ここから {extracted_data} を参照できる（Step 1 が保存した）
# =====================================================
validator_agent = LlmAgent(
    name="validator",
    model=settings.default_model,
    description="抽出されたデータの品質を検証する",
    instruction="""
あなたはデータ品質エンジニアです。

以下の抽出済みデータを検証してください:

--- 抽出済みデータ ---
{extracted_data}
---

以下の観点でデータ品質を評価してください:
1. **完全性**: 必須フィールドに欠損はないか
2. **一貫性**: データ型や形式が統一されているか
3. **正確性**: 明らかに異常な値はないか（範囲外の数値、不正な日付など）
4. **ユニーク性**: 重複レコードはないか

検証結果:
- 品質スコア: X/100
- 検出した問題リスト（問題がない場合は「問題なし」）
- 次のステップへの推奨事項
""",
    output_key="validation_result",
)

# =====================================================
# Step 3: データ変換エージェント
# =====================================================
transformer_agent = LlmAgent(
    name="transformer",
    model=settings.default_model,
    description="データを分析に適した形式に変換・整形する",
    instruction="""
あなたはデータエンジニアです。

以下のデータを分析に適した形式に変換してください:

--- 抽出済みデータ ---
{extracted_data}

--- 検証結果 ---
{validation_result}

変換タスク:
1. 検証で発見した問題を可能な範囲で修正
2. 数値データの正規化（必要な場合）
3. 文字列の標準化（大文字小文字、スペースなど）
4. 集計値の追加（合計、平均、最大/最小など）

変換後のデータサマリーと適用した変換内容を明確に記述してください。
""",
    output_key="transformed_data",
)

# =====================================================
# Step 4: サマリーエージェント
# =====================================================
summarizer_agent = LlmAgent(
    name="summarizer",
    model=settings.default_model,
    description="ETL パイプラインの実行結果をサマリーレポートとして出力する",
    instruction="""
あなたはデータアナリストです。

以下の ETL パイプライン全体の処理結果をまとめてください:

--- 抽出結果 ---
{extracted_data}

--- 検証結果 ---
{validation_result}

--- 変換済みデータ ---
{transformed_data}

以下の形式でエグゼクティブサマリーを作成してください:

# ETL パイプライン実行レポート

## 処理概要
- 処理ステップ数、処理したレコード数

## データ品質サマリー
- 品質スコアと主要な問題

## 変換内容
- 適用した変換の一覧

## 最終データの特徴
- 変換後データの主要な統計情報

## 推奨アクション
- データを活用する上での注意点や次のステップ
""",
)

# =====================================================
# Sequential パターンのオーケストレーター
# =====================================================
root_agent = SequentialAgent(
    name="etl_pipeline",
    description="データ抽出・検証・変換・サマリーを順次実行する ETL パイプライン",
    sub_agents=[
        extractor_agent,    # Step 1: 抽出（ユーザーメッセージから直接）
        validator_agent,    # Step 2: 検証 ({extracted_data} を参照)
        transformer_agent,  # Step 3: 変換 ({extracted_data}, {validation_result} を参照)
        summarizer_agent,   # Step 4: サマリー（全結果を参照）
    ],
)
