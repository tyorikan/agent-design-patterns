# AI Agent Design Patterns - 要件定義書

## プロジェクト目的

Google Cloud のアーキテクチャガイドに基づき、AI エージェントのデザインパターンをハンズオンで習得するための
学習コンテンツを構築する。Single Agent から始まり、段階的に複雑なマルチエージェントシステムを
実装できるスキルを身につけることを目的とする。

## ターゲット

- Google Cloud Japan アプリケーションモダナイゼーションスペシャリスト
- Cloud Run、GKE、Vertex AI、Pub/Sub の知識を持つエンジニア
- AI エージェントの設計・実装スキルを強化したいエンジニア

## 機能要件

### 学習コンテンツ

各デザインパターンについて以下を提供する：

1. **概念説明** (README.md)
   - パターンの概要と特徴
   - いつ使うべきか（適用条件）
   - アーキテクチャ図
   - トレードオフ（レイテンシ・コスト・複雑性）

2. **実装例**
   - 動作する Python コード
   - 実用的なユースケース
   - エラーハンドリング

3. **実行スクリプト**
   - `run.py`: 対話的実行
   - `demo.py`: デモシナリオの自動実行

4. **テスト**
   - 主要機能のユニットテスト

### デザインパターン（実装対象）

| Lv | パターン | ユースケース |
|---|---|---|
| 1 | Single Agent | GCP ドキュメント Q&A |
| 2 | ReAct Pattern | 株価分析 |
| 3 | Sequential | ETL データパイプライン |
| 4 | Parallel | マルチソース市場調査 |
| 5 | Loop | コード生成 & テスト実行 |
| 6 | Review & Critique | ブログ記事品質チェック |
| 7 | Iterative Refinement | 技術ドキュメント自動作成 |
| 8 | Coordinator | カスタマーサポート自動化 |
| 9 | Hierarchical | 競合分析レポート |
| 10 | Swarm | 新製品設計コンサルティング |
| Bonus | Human-in-the-Loop | コンプライアンス承認フロー |
| Bonus | Agentic Pipeline | PGE 自律コード生成パイプライン（ADK BaseAgent + Antigravity SDK） |
| Capstone | Enterprise Research Agent | 全パターン統合 |

### PGE パイプライン（Agentic Pipeline）

- **Planner-Generator-Evaluator ループ**による自律コード生成
  - Planner: 要件→実装計画、Generator: コード生成+セルフチェック、Evaluator: 品質評価
- **6段階の verdict 判定ロジック**（優先度順）:
  1. 最大反復回数到達 → APPROVED
  2. ブロッカー検出 → REVISE
  3. リグレッション検出（前回比スコア低下） → REVISE
  4. 閾値超過（score ≥ `approval_threshold`） → APPROVED
  5. 改善停滞（改善幅 < `min_improvement`） → APPROVED
  6. LLM verdict をそのまま採用
- **Generator の ruff/pytest セルフチェック**: `ruff check .` → 修正 → `pytest` → 修正 → submit
- **dynamic output_dir**: 任意ディレクトリを対象にコード生成可能
- **`adk run`** での実行サポート

## 技術要件

- Python 3.12+
- Google ADK Python 2.1+（Workflow API 使用）
- Antigravity SDK（google-antigravity） — Gemini ベースの自律エージェント
- Vertex AI Gemini 3.5 Flash（デフォルト）
- パッケージ管理: pip (pyproject.toml) + uv (Docker)
- テスト: pytest + pytest-asyncio（2層テストピラミッド）

## 非機能要件

- 各パターンは独立して実行可能
- 共通ライブラリは `shared/` に集約
- 設定は環境変数で管理（`.env`）
  - `approval_threshold`: Evaluator スコア閾値（デフォルト 80）
  - `min_improvement`: 改善停滞判定の最低改善幅（デフォルト 5）
  - `gemini_api_key`: Antigravity SDK ローカル実行用 API キー
- 全コードに型アノテーション
