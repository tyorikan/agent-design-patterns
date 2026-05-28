"""Pydantic スキーマ定義。

Antigravity Agent の structured output で使用する。
ノード間の受け渡しデータを型保証し、自律エージェント出力の予測不能性を軽減する。
"""

from enum import Enum

from pydantic import BaseModel, Field


class Severity(str, Enum):
    """品質問題の重大度。"""

    CRITICAL = "CRITICAL"  # 必ず修正が必要（テスト失敗、セキュリティ脆弱性）
    HIGH = "HIGH"          # 修正推奨（エラーハンドリング不足、型不整合）
    MEDIUM = "MEDIUM"      # 改善推奨（命名、ドキュメント不足）
    LOW = "LOW"            # Nice to have（コードスタイル等）


class Issue(BaseModel):
    """評価で検出された個別課題。"""

    severity: Severity = Field(description="問題の重大度")
    description: str = Field(description="問題の説明")
    file: str = Field(default="", description="対象ファイル")
    suggestion: str = Field(default="", description="修正提案")


class PlanOutput(BaseModel):
    """Planner Agent の出力スキーマ。"""

    architecture: str = Field(
        description="設計方針の概要（モジュール構成、設計パターン、責務分離の方針）"
    )
    modules: list[str] = Field(
        description="作成するモジュール一覧（例: main.py, models.py, tests/test_main.py）"
    )
    test_strategy: str = Field(
        description="テスト戦略（単体テスト・統合テストの方針、カバレッジ目標）"
    )
    directory_structure: str = Field(
        description="ディレクトリ構成（ツリー形式）"
    )


class ArtifactOutput(BaseModel):
    """Generator Agent の出力スキーマ。"""

    files_created: list[str] = Field(
        description="作成したファイルパスのリスト"
    )
    summary: str = Field(
        description="実装内容のサマリー"
    )


class EvaluationOutput(BaseModel):
    """Evaluator Agent の出力スキーマ。

    REVISE 条件:
    - score < approval_threshold かつ改善可能 → verdict = "REVISE"
    - score >= approval_threshold → verdict = "APPROVED"
    - 改善停滞（前回との差 < min_improvement） → verdict = "APPROVED"
    """

    score: int = Field(
        ge=0, le=100,
        description="品質スコア（0-100）。80 以上で APPROVED"
    )
    test_result: str = Field(
        description="pytest 実行結果のサマリー（passed/failed/error）"
    )
    lint_result: str = Field(
        description="ruff 実行結果のサマリー（エラー数・警告数）"
    )
    execution_result: str = Field(
        default="",
        description="ビルド・起動テストの結果サマリー（import チェック、docker build 等）"
    )
    issues: list[Issue] = Field(
        description="検出された品質問題のリスト（重大度付き）"
    )
    suggestions: list[str] = Field(
        description="改善提案のリスト"
    )
    verdict: str = Field(
        description="判定結果: 'APPROVED' または 'REVISE'"
    )
    reasoning: str = Field(
        description="判定理由の詳細説明"
    )
