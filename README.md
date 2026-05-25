# AI Agent Design Patterns

Google Cloud のアーキテクチャガイドに基づく、AI エージェントデザインパターンのハンズオン実装コンテンツ。

Single Agent から Swarm まで、段階的に複雑なマルチエージェントシステムを実装することで、
実務で使える AI エージェント開発スキルを身につけることを目的とする。

## 🚀 クイックスタート

### 前提条件

- Python 3.12+
- Google Cloud プロジェクト（Vertex AI API 有効）
- `gcloud auth application-default login` 済み

### セットアップ

```bash
# リポジトリをクローン
git clone <repo-url>
cd agent-design-patterns

# 環境変数を設定
cp .env.example .env
# .env を編集して GOOGLE_CLOUD_PROJECT を設定

# venv 作成 & 依存関係インストール（pyproject.toml から一括）
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 実行方法

```bash
# 1. 各パターンのデモ実行
PYTHONPATH=. python3 patterns/01_single_agent/demo.py

# 2. ADK Web UI で対話的にテスト
docker compose up
# → ブラウザで http://localhost:8080 を開く
# → エージェントを選択して対話

# 3. テスト実行
pytest tests/unit/ -v         # Lv.1 ユニットテスト（約1秒）
pytest tests/integration/ -v  # Lv.2 統合テスト（Vertex AI 必要、約13分）
pytest tests/ -v              # 全テスト
```

## 📚 学習ロードマップ

### 決定論的ワークフロー（Deterministic Workflows）

予測可能・順序固定・事前定義のフロー。モデルオーケストレーション不要。

| Level | パターン | ディレクトリ | ユースケース | ADK クラス |
|-------|---------|------------|------------|-----------|
| Lv.1 | **Single Agent** | `patterns/01_single_agent/` | GCP ドキュメント Q&A | `LlmAgent` |
| Lv.2 | **ReAct Pattern** | `patterns/02_react_pattern/` | 技術調査（Thought/Action/Obs 可視化） | `LlmAgent` |
| Lv.3 | **Sequential** | `patterns/03_sequential/` | ETL データパイプライン | `SequentialAgent` |
| Lv.4 | **Parallel** | `patterns/04_parallel/` | マルチソース AI ニュース集約 | `ParallelAgent` |

### 反復ワークフロー（Iterative Workflows）

品質基準達成まで繰り返す処理。

| Level | パターン | ディレクトリ | ユースケース | ADK クラス |
|-------|---------|------------|------------|-----------|
| Lv.5 | **Loop** | `patterns/05_loop/` | コード生成 & テストループ | `LoopAgent` |
| Lv.6 | **Review & Critique** | `patterns/06_review_critique/` | ブログ記事品質保証 | `LoopAgent` |
| Lv.7 | **Iterative Refinement** | `patterns/07_iterative_refinement/` | 技術ドキュメント自己改善 | `LoopAgent` |

### 動的オーケストレーション（Dynamic Orchestration）

LLM が動的にルーティング・タスク分解を行う。

| Level | パターン | ディレクトリ | ユースケース | ADK クラス |
|-------|---------|------------|------------|-----------|
| Lv.8 | **Coordinator** | `patterns/08_coordinator/` | カスタマーサポートルーター | `LlmAgent` |
| Lv.9 | **Hierarchical** | `patterns/09_hierarchical/` | 競合分析（多層分解） | `LlmAgent` 多層 |
| Lv.10 | **Swarm** | `patterns/10_swarm/` | 製品設計コンセンサス | `LoopAgent` + 多エージェント |

### 特殊パターン

| Level | パターン | ディレクトリ | ユースケース | ADK クラス |
|-------|---------|------------|------------|-----------|
| Bonus | **Human-in-the-Loop** | `patterns/11_human_in_the_loop/` | コンテンツ承認ワークフロー | カスタム |
| 🏆 | **Capstone** | `patterns/capstone/` | 全パターン統合 企業分析レポート | 全クラス統合 |

## 🏗️ パターン選択フローチャート

```
タスクの特性を評価:
  │
  ├─ フローが固定されている？
  │   ├─ 線形処理 → Lv.3 Sequential
  │   ├─ 並列可能 → Lv.4 Parallel
  │   └─ 繰り返し → Lv.5 Loop
  │
  ├─ 品質向上のための反復が必要？
  │   ├─ 別の視点で批評 → Lv.6 Review & Critique
  │   └─ 自己改善 → Lv.7 Iterative Refinement
  │
  ├─ 動的なルーティングが必要？
  │   ├─ シンプル + ツール → Lv.1 Single Agent / Lv.2 ReAct
  │   ├─ 専門エージェントへの振り分け → Lv.8 Coordinator
  │   └─ 多層のタスク分解 → Lv.9 Hierarchical
  │
  ├─ 複数視点でのコンセンサスが必要？
  │   └→ Lv.10 Swarm
  │
  └─ 人間の承認が必要？
      └→ Lv.11 Human-in-the-Loop（他パターンと組み合わせ）
```

## 🔀 パターンの組み合わせ

実務では複数のパターンを組み合わせることが多い。Capstone エージェントがその好例：

```
[Coordinator (Lv.8)]
    │
    ▼
[SequentialAgent (Lv.3)]
    ├── [ParallelAgent (Lv.4)]      ← 3ソース並列データ収集
    │   ├── Web Researcher
    │   ├── Tech Researcher
    │   └── Finance Researcher
    ├── [Analysis Agent]             ← SWOT 分析
    └── [LoopAgent (Lv.5)]           ← 品質改善ループ
        ├── Report Writer (Lv.6)
        └── Report Critic (Lv.6)
```

**組み合わせの原則:**
1. **外側に SequentialAgent** → 全体のパイプライン制御
2. **独立タスクは ParallelAgent** → レイテンシ削減
3. **品質保証は LoopAgent** → Review & Critique で反復改善
4. **柔軟なルーティングは LlmAgent** → Coordinator パターン

## 🔑 ADK の重要知識

### `{変数名}` はセッション状態から参照

```python
# ✅ 正しい使い方: 前のエージェントが output_key で保存した値を参照
agent_b = LlmAgent(
    instruction="前の結果: {result_from_agent_a}",  # agent_a の output_key="result_from_agent_a"
)

# ❌ NG: 最初のエージェントでセッション状態にないキーを参照するとエラー
first_agent = LlmAgent(
    instruction="タスク: {task_name}",  # KeyError! task_name はセッション状態にない
)
```

### `output_key` でエージェント間データを受け渡す

```python
agent_a = LlmAgent(
    output_key="my_result",  # セッション状態に "my_result" として保存
)

agent_b = LlmAgent(
    instruction="{my_result} を使って処理してください",  # agent_a の結果を参照
)
```

### ParallelAgent の各エージェントは異なる `output_key` を使う

```python
# ⚠️ 各エージェントで別々のキーを使わないと結果が上書きされる
ParallelAgent(
    sub_agents=[
        LlmAgent(output_key="source_a"),  # ← 固有のキー
        LlmAgent(output_key="source_b"),  # ← 固有のキー
        LlmAgent(output_key="source_c"),  # ← 固有のキー
    ]
)
```

## 🧪 テスト

テストピラミッドに基づく2層構造。詳細は [tests/README.md](tests/README.md) を参照。

```
tests/
├── unit/                        # Lv.1: 決定的テスト（LLM なし、約1秒）
│   ├── test_config.py           # 設定・環境変数の検証
│   └── test_agent_structure.py   # 全12パターンのエージェント構成検証
└── integration/                 # Lv.2: 統合テスト（実 LLM、約13分）
    └── test_patterns.py         # プロパティベース + トラジェクトリ検証
```

### テスト実行コマンド

```bash
# Lv.1 ユニットテスト（高速、CI の必須ステップ）
pytest tests/unit/ -v

# Lv.2 統合テスト（Vertex AI ADC 必要）
pytest tests/integration/ -v

# 全テスト
pytest tests/ -v

# カバレッジ付き
pytest tests/ --cov=shared --cov-report=term-missing

# 特定のテストクラスのみ
pytest tests/unit/test_agent_structure.py::TestSwarmStructure -v
```

### テストの書き方

テスト規約は [CONTRIBUTING.md](CONTRIBUTING.md) を参照。

## 📦 技術スタック

| 技術 | バージョン | 用途 |
|------|-----------|------|
| `google-adk` | 1.19.0+ | エージェントフレームワーク |
| `google-genai` | 1.52.0+ | Gemini モデルクライアント |
| `Gemini 3.5 Flash` | - | デフォルト LLM |
| `Vertex AI` | - | エンドポイント（ADC 認証） |
| `pydantic-settings` | 2.4.0+ | 設定管理 |
| `rich` | 13.9.0+ | デモの見やすい出力 |
| `pytest` | 8.3.0+ | テストフレームワーク |
| `ruff` | 0.7.0+ | リント & フォーマット |

## 🔐 認証

```bash
# Vertex AI ADC 認証（推奨）
gcloud auth application-default login

# .env に設定
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=global
GOOGLE_GENAI_USE_VERTEXAI=True
DEFAULT_MODEL=gemini-3.5-flash
```

## 🐳 Docker / ADK Web UI

```bash
# ADK Web UI 起動（全パターンを対話的にテスト）
docker compose up

# → http://localhost:8080 を開く
# → 左パネルでエージェントを選択
# → チャットで質問を入力

# 特定パターンのみ実行
docker compose run --rm runner bash -c "PYTHONPATH=/app python3 patterns/01_single_agent/demo.py"
```

**Docker の仕組み:**
- `Dockerfile` は uv を使って依存関係をインストール
- `docker-compose.yml` でローカルの ADC クレデンシャルをマウント
- `adk web` コマンドで全 `patterns/*/agent.py` を自動検出

## 🔧 トラブルシューティング

### よくあるエラー

| エラー | 原因 | 解決策 |
|--------|------|--------|
| `ValidationError: google_cloud_project` | `.env` にプロジェクトID未設定 | `cp .env.example .env` して編集 |
| `google.auth.exceptions.DefaultCredentialsError` | ADC 認証が未完了 | `gcloud auth application-default login` |
| `KeyError: '{variable_name}'` | セッション状態にない変数を参照 | 最初のエージェントでは `{変数}` を使わない |
| `ModuleNotFoundError: No module named 'shared'` | PYTHONPATH 未設定 | `PYTHONPATH=. python3 ...` で実行 |
| `Permission denied (Vertex AI)` | API 未有効化 | `gcloud services enable aiplatform.googleapis.com` |
| `LoopAgent が終了しない` | 終了条件がない | `max_iterations` を必ず設定 |

### デバッグのコツ

```bash
# ADK イベントストリームの確認
# → patterns/02_react_pattern/agent.py の run_with_react_trace() を参考に

# 環境変数の確認
python3 -c "from shared.config import get_settings; print(get_settings())"

# 特定パターンの動作確認
PYTHONPATH=. python3 -c "from patterns.capstone.agent import root_agent; print(root_agent.name)"
```

## 📖 各パターンの README

各パターンディレクトリに詳細な README があります:
- **概念と図解** — ASCII アーキテクチャ図付き
- **いつ使うか** — 適用条件と限界
- **前のパターンとの違い** — 比較表
- **トレードオフ** — コスト・レイテンシ・複雑性の評価
- **実行方法** — コマンド例
- **学習ポイント** — 習得すべき ADK の知識
- **次のステップ** — 次のパターンへのリンク

## 🤝 コントリビューション

[CONTRIBUTING.md](CONTRIBUTING.md) を参照してください。

## 📚 参考資料

### Google Cloud Architecture Center

- [Agentic AI architecture guides（概要）](https://docs.cloud.google.com/architecture/agentic-ai-overview)
- [Choose architecture components for an agentic AI system](https://docs.cloud.google.com/architecture/choose-agentic-ai-architecture-components)
- [Choose a design pattern for an agentic AI system](https://docs.cloud.google.com/architecture/choose-design-pattern-agentic-ai-system)
- [Build a multiagent AI system](https://docs.cloud.google.com/architecture/multiagent-ai-system)
- [Build a single-agent AI system using ADK and Cloud Run](https://docs.cloud.google.com/architecture/single-agent-ai-system-adk-cloud-run)

### Google ADK / Vertex AI

- [Google ADK Python ドキュメント](https://google.github.io/adk-docs/)
- [Vertex AI Gemini API](https://cloud.google.com/vertex-ai/generative-ai/docs/gemini-api)
