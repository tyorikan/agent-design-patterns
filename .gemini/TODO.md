# TODO

## スキル構築
- [x] skills/adk-python/SKILL.md - Google ADK Python スキル
- [x] skills/agent-design-patterns/SKILL.md - デザインパターン選択ガイド
- [x] skills/a2a-protocol/SKILL.md - A2A プロトコルスキル
- [x] skills/vertex-ai-adk-setup/SKILL.md - Vertex AI セットアップスキル
- [x] skills/adk-testing-debugging/SKILL.md - テスト・デバッグスキル

## プロジェクト基盤
- [x] pyproject.toml の作成
- [x] shared/config.py の実装
- [x] shared/demo_runner.py の実装
- [x] .env.example の作成
- [x] README.md（プロジェクト全体説明）の作成
- [x] conftest.py の作成
- [x] Dockerfile の作成
- [x] docker-compose.yml の作成
- [x] CONTRIBUTING.md の作成

## パターン実装 Phase 2（基礎）
- [x] 01_single_agent（agent.py + demo.py + tests/）
- [x] 02_react_pattern（agent.py + demo.py + tests/）
- [x] 03_sequential（agent.py + demo.py + tests/）
- [x] 04_parallel（agent.py + demo.py + tests/）
- [x] 05_loop（agent.py + demo.py + tests/）

## パターン実装 Phase 3（応用）
- [x] 06_review_critique（agent.py + demo.py + tests/）
- [x] 07_iterative_refinement（agent.py + demo.py + tests/）
- [x] 08_coordinator（agent.py + demo.py + tests/）

## パターン実装 Phase 4（高度）
- [x] 09_hierarchical（agent.py + demo.py + tests/）
- [x] 10_swarm（agent.py + demo.py + tests/）
- [x] 11_human_in_the_loop（agent.py + demo.py + tests/）

## Capstone
- [x] enterprise_research_agent の設計
- [x] enterprise_research_agent の実装（agent.py + demo.py + tests/）

## テスト
- [x] tests/test_all_patterns.py（全パターン統合テスト） → 廃止済
- [x] 各パターンのローカルテスト（tests/test_agent.py） → 廃止済
- [x] テストピラミッド再構築（Lv.1 ユニット + Lv.2 統合）
- [x] tests/unit/test_config.py — 設定検証
- [x] tests/unit/test_agent_structure.py — 全12パターン構成検証
- [x] tests/integration/test_patterns.py — プロパティ + トラジェクトリ検証
- [x] tests/README.md — テスト戦略ドキュメント

## ドキュメント
- [x] 各パターン README.md の標準フォーマット化
- [x] プロジェクト README.md の充実化
- [x] CONTRIBUTING.md の作成
- [x] .gemini/DESIGN.md の最新化
- [x] 全ドキュメントのテスト再構築対応更新
