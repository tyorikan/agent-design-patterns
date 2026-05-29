# TODO

## スキル構築
- [x] skills/adk-python/SKILL.md - Google ADK Python スキル
- [x] skills/agent-design-patterns/SKILL.md - デザインパターン選択ガイド
- [x] skills/a2a-protocol/SKILL.md - A2A プロトコルスキル
- [x] skills/vertex-ai-adk-setup/SKILL.md - Vertex AI セットアップスキル
- [x] skills/adk-testing-debugging/SKILL.md - テスト・デバッグスキル
- [x] skills/agentic-pipeline/SKILL.md - PGE 自律コード生成パイプラインスキル
- [x] skills/ai-agent-testing-strategy/SKILL.md - AI エージェントテスト戦略スキル

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
- [x] p01_single_agent（agent.py + demo.py + tests/）
- [x] p02_react_pattern（agent.py + demo.py + tests/）
- [x] p03_sequential（agent.py + demo.py + tests/）
- [x] p04_parallel（agent.py + demo.py + tests/）
- [x] p05_loop（agent.py + demo.py + tests/）

## パターン実装 Phase 3（応用）
- [x] p06_review_critique（agent.py + demo.py + tests/）
- [x] p07_iterative_refinement（agent.py + demo.py + tests/）
- [x] p08_coordinator（agent.py + demo.py + tests/）

## パターン実装 Phase 4（高度）
- [x] p09_hierarchical（agent.py + demo.py + tests/）
- [x] p10_swarm（agent.py + demo.py + tests/）
- [x] p11_human_in_the_loop（agent.py + demo.py + tests/）

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
- [x] docs/v1-to-v2-migration-guide.md 作成
- [x] ドキュメント包括的アップデート（REQUIREMENTS.md, DESIGN.md, TODO.md, TIPS.md）

## ADK v2 移行（v2 ブランチ）
- [x] google-adk>=2.1.0, google-genai>=1.72.0 にアップグレード
- [x] SequentialAgent → Workflow チェーンタプル（03, capstone）
- [x] ParallelAgent → Workflow ネストタプル fan-out/fan-in（04, capstone）
- [x] LoopAgent → Workflow 条件付きサイクル（05, 06, 07, 10, capstone）
- [x] Human-in-the-Loop → Workflow パイプライン（11）
- [x] deprecated import ゼロ確認
- [x] test_agent_structure.py を Workflow 対応に書き直し
- [x] 全50テスト PASS 確認
- [x] .gemini/ ドキュメント更新（DESIGN.md, REQUIREMENTS.md, TODO.md）
- [x] 各パターン README.md の v2 更新
- [x] プロジェクト README.md の v2 更新
- [x] .agents/skills/*.md の v2 更新

## Agentic Pipeline（PGE 自律コード生成パイプライン）
- [x] agentic_pipeline の設計（agent.py, tools.py, prompts.py, schemas.py）
- [x] agentic_pipeline の実装完了
- [x] agentic_pipeline のテスト完了
- [x] config.py PGE 設定拡張（approval_threshold, min_improvement, gemini_api_key）
