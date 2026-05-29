# Contributing

AI Agent Design Patterns プロジェクトへのコントリビューションガイドです。

## 開発環境のセットアップ

```bash
# リポジトリのクローン
git clone <repo-url>
cd agent-design-patterns

# Python 3.12+ が必要
python3 --version

# venv 作成 & 依存関係インストール
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 環境変数の設定
cp .env.example .env
# .env を編集して GOOGLE_CLOUD_PROJECT を設定

# Vertex AI 認証
gcloud auth application-default login
```

## プロジェクト構造

```
agent-design-patterns/
├── patterns/                 # 各デザインパターンの実装
│   ├── p01_single_agent/     # Lv.1〜11 + capstone
│   │   ├── README.md        # 概念・図解・学習ポイント
│   │   ├── agent.py         # エージェント定義（root_agent を export）
│   │   └── demo.py          # デモスクリプト
│   └── ...
├── shared/                   # 共通ライブラリ
│   ├── config.py            # Settings + @lru_cache
│   └── demo_runner.py       # デモ実行ユーティリティ
├── tests/                    # テストピラミッド
│   ├── README.md            # テスト戦略ドキュメント
│   ├── unit/                # Lv.1: 決定的テスト（LLM なし）
│   └── integration/         # Lv.2: 統合テスト（実 LLM）
├── conftest.py               # テスト共通ヘルパー
├── pyproject.toml
└── README.md
```

## 新しいパターンの追加方法

### 1. ディレクトリ作成

```bash
mkdir -p patterns/XX_pattern_name
```

### 2. 必須ファイル

| ファイル | 内容 |
|---------|------|
| `README.md` | 概念・図解・トレードオフ・学習ポイント |
| `agent.py` | エージェント定義（`root_agent` を export） |
| `demo.py` | デモスクリプト |

### 3. agent.py のルール

```python
# 共通パターン: shared/config.py から設定を読み込む
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from shared.config import get_settings

settings = get_settings()

# root_agent を定義（ADK Web UI から参照される）
root_agent = LlmAgent(
    name="unique_agent_name",  # ユニークな名前
    model=settings.default_model,
    description="...",
    instruction="...",
)
```

### 4. README.md の標準フォーマット

```markdown
# Lv.X パターン名

## 概念
## いつ使うか
## 前のパターンとの違い（比較表）
## このデモのユースケース
## アーキテクチャ（ASCII 図）
## トレードオフ（表）
## 実行方法
## 学習ポイント
## 次のステップ
```

### 4. テストの追加方法

パターンを追加したら、以下の2ファイルにテストを追加する:

#### Lv.1 構成テスト (`tests/unit/test_agent_structure.py`)

```python
class TestNewPatternStructure:
    def setup_method(self):
        self.mod = load_pattern_agent("XX_pattern_name")

    def test_root_agent_name(self):
        assert self.mod.root_agent.name == "expected_name"

    # LlmAgent パターンの場合
    def test_sub_agents_count(self):
        assert len(self.mod.root_agent.sub_agents) == N

    # Workflow パターンの場合
    def test_root_agent_is_workflow(self):
        from google.adk.workflow import Workflow
        assert isinstance(self.mod.root_agent, Workflow)

    def test_graph_has_expected_nodes(self):
        node_names = [n.name for n in self.mod.root_agent.graph.nodes]
        assert "expected_node" in node_names
```

#### Lv.2 統合テスト (`tests/integration/test_patterns.py`)

プロパティベース + トラジェクトリ検証を使用する:

```python
class TestNewPattern:
    @pytest.mark.asyncio
    async def test_pattern_works(self):
        mod = load_pattern_agent("XX_pattern_name")
        response, trajectory = await run_agent_trajectory(
            mod.root_agent, "app_name", "テストクエリ"
        )
        # プロパティ: 十分な長さの出力
        assert len(response) > 100
        # トラジェクトリ: 正しいエージェントが発言
        assert "expected_agent" in trajectory
```

詳細は [tests/README.md](tests/README.md) を参照。

## コーディング規約

### Python コード

- **フォーマッター**: `ruff format`
- **リンター**: `ruff check`
- **型チェック**: `mypy`
- **行長**: 100文字
- **型アノテーション**: 必須
- **docstring**: 全ての関数・クラスに必須

```bash
# リント & フォーマット
ruff check --fix .
ruff format .

# 型チェック
mypy shared/
```

### コミットメッセージ

```
feat(pattern-XX): パターン名の追加
fix(pattern-XX): バグ修正の説明
docs(pattern-XX): README の更新
test(pattern-XX): テストの追加
chore: プロジェクト設定の変更
```

## テストの実行

```bash
# Lv.1 ユニットテスト（高速、CI の必須ステップ）
pytest tests/unit/ -v

# Lv.2 統合テスト（Vertex AI ADC 必要）
pytest tests/integration/ -v

# 全テスト
pytest tests/ -v

# カバレッジ付き
pytest tests/ --cov=shared --cov-report=term-missing
```

## デモの実行

```bash
# 各パターンのデモ
PYTHONPATH=. python3 patterns/p01_single_agent/demo.py

# ADK Web UI（全パターンを対話的にテスト）
docker compose up
# → http://localhost:8080
```

## レビューのチェックリスト

- [ ] `agent.py` に `root_agent` が定義されている
- [ ] `demo.py` が単独で実行できる
- [ ] `README.md` が標準フォーマットに従っている
- [ ] `tests/unit/test_agent_structure.py` に構成テストが追加されている
- [ ] `tests/integration/test_patterns.py` に統合テストが追加されている
- [ ] `ruff check` がパスする
- [ ] `pytest tests/unit/ -v` がパスする
