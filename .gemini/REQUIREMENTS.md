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
| Capstone | Enterprise Research Agent | 全パターン統合 |

## 技術要件

- Python 3.12+
- Google ADK Python 1.19+
- Vertex AI Gemini 3.5 Flash（デフォルト）
- パッケージ管理: pip (pyproject.toml) + uv (Docker)
- テスト: pytest + pytest-asyncio（2層テストピラミッド）

## 非機能要件

- 各パターンは独立して実行可能
- 共通ライブラリは `shared/` に集約
- 設定は環境変数で管理（`.env`）
- 全コードに型アノテーション
