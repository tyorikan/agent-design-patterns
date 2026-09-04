# AI Agent Design Patterns スキルセット

このディレクトリには、AI エージェント開発に必要なスキル定義が含まれています。

## スキル一覧

| スキル | 説明 | 参照タイミング |
|---|---|---|
| [adk-python](./adk-python/SKILL.md) | Google ADK Python の実装スキル | エージェント実装時 **必須** |
| [agent-design-patterns](./agent-design-patterns/SKILL.md) | デザインパターン選択ガイド | アーキテクチャ決定時 **必須** |
| [a2a-protocol](./a2a-protocol/SKILL.md) | A2A プロトコルの実装スキル | クロスフレームワーク連携時 |
| [vertex-ai-adk-setup](./vertex-ai-adk-setup/SKILL.md) | Vertex AI + ADK セットアップ | 環境構築時 |
| [adk-testing-debugging](./adk-testing-debugging/SKILL.md) | ADK API レベルのテスト・デバッグ | テスト実装時 |
| [ai-agent-testing-strategy](./ai-agent-testing-strategy/SKILL.md) | テスト戦略の設計判断・非決定性対策 | テスト設計・パッケージ更新時 **必須** |
| [agentic-pipeline](./agentic-pipeline/SKILL.md) | PGE 自律コード生成パイプラインの設計・実装ガイド | PGE パイプライン実装時 |
| [agents-cli-deploy-runtime](./agents-cli-deploy-runtime/SKILL.md) | agents-cli + Agent Runtime デプロイ・連携 | **Agent Runtime デプロイ時 必須** |

## 推奨する参照順序

1. `vertex-ai-adk-setup` → 環境を構築する
2. `agent-design-patterns` → どのパターンを実装するか決める
3. `adk-python` → 実際にコードを書く
4. `a2a-protocol` → 複数サービス間を繋ぐ場合
5. `ai-agent-testing-strategy` → テスト戦略を設計する
6. `adk-testing-debugging` → テストを書く

## 技術スタック

- **言語**: Python 3.12+
- **パッケージ管理**: pip (pyproject.toml) + uv (Docker)
- **エージェントフレームワーク**: Google ADK Python 2.8.0 (Workflow API)
- **LLM**: Vertex AI Gemini 3.8 Flash (location=global, Thinking Level 対応)
- **エージェント間通信**: A2A Protocol
- **外部ツール連携**: MCP (Model Context Protocol)
- **デプロイ**: Cloud Run / Vertex AI Agent Engine
