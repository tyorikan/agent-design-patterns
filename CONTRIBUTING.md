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
# .env を編集して GOOGLE_CLOUD_PROJECT を設定（GOOGLE_CLOUD_LOCATION=global 推奨）

# Google Cloud ADC 認証
gcloud auth application-default login
```

## プロジェクト構造（3 トラック構成）

```
agent-design-patterns/
├── patterns/                     # Track 1: 基礎・応用オーケストレーションパターン（Lv.1〜11 + Capstone + PGE）
│   └── p01_single_agent/
│       ├── README.md            # 概念・図解・トレードオフ・学習ポイント
│       ├── agent.py             # エージェント定義（root_agent を export）
│       └── demo.py              # デモスクリプト
├── agents_cli_patterns/          # Track 2: agents-cli によるライフサイクル管理デザインパターン（CLI-01〜04）
│   └── cli01_spec_driven_agent/
│       ├── README.md
│       ├── agent.yaml           # 宣言的マニフェスト
│       ├── specs/               # AGENT_SPEC.md 等の仕様書
│       └── app/                 # agent.py（app と root_agent を export）
├── production_patterns/          # Track 3: 本番運用デザインパターン（PROD-01〜06）
│   └── prod01_contract_based_execution/
│       ├── README.md
│       ├── agent.py             # Workflow / Plugin / Agent 実装
│       └── demo.py
├── shared/                       # 共通ライブラリ
│   ├── config.py                # Settings（Gemini 4 Hydrogen / global 既定）
│   └── demo_runner.py           # LlmAgent / Workflow 両対応のデモ実行ランナー
├── docs/                         # 移行ガイド等の技術ドキュメント
├── tests/                        # テストピラミッド
│   ├── README.md
│   ├── unit/                    # Lv.1: 決定的テスト + ScriptedLlm インプロセス結合テスト
│   └── integration/             # Lv.2: 実 LLM 統合テスト
├── conftest.py                   # 3 トラック共通テストヘルパー
├── pyproject.toml
└── README.md
```

## デザインパターンの記述原則

新しいパターンを追加する際は、単なるサンプルスクリプトではなく**再利用可能なデザインパターン**として以下を満たしてください。

1. **平易で自明なソフトウェア工学用語を使う**: 独自の造語、製造業スラング、文脈を知らない読者に伝わらない比喩表現は使用しない。
2. **「できること」だけでなく「できないこと・不向きな条件」を明記する**: すべてのパターンにはトレードオフ（レイテンシ増加、実装コスト、統計的前提など）が存在するため、`いつ使うか` セクションに適用限界を正直に記載する。
3. **公開リポジトリの衛生管理**: 特定の顧客名、内部プロジェクト名、実プロジェクト ID、認証情報は一切含めない。

### README.md の標準フォーマット

```markdown
# パターン名

## 概念（Mermaid または ASCII 図解を含む）
## いつ使うか（適している場合 / 不向きな場合・できないこと）
## 関連パターンとの違い（比較表）
## このデモのユースケース
## アーキテクチャと実装のポイント
## トレードオフ（表）
## 実行方法
## 学習ポイント
## 次のステップ
```

## コーディング規約

- **フォーマッター / リンター**: `ruff format`, `ruff check`
- **型チェック**: `mypy`
- **行長**: 100 文字
- **型アノテーション・Docstring**: 全ての公開関数・クラスに必須

```bash
# リント & 型チェック
.venv/bin/ruff check .
.venv/bin/mypy shared/ production_patterns/
```

## テストの実行

```bash
# Lv.1 ユニットテスト（外部通信なし・約 4 秒、CI 必須ステップ）
.venv/bin/pytest tests/unit/ -v

# Lv.2 統合テスト（Google Cloud ADC 必要）
.venv/bin/pytest tests/integration/ -v
```

## レビューのチェックリスト

- [ ] `agent.py` に `root_agent`（および必要に応じて `app`）が定義されている
- [ ] `README.md` が標準フォーマットに従い、適用限界（できないこと）が明記されている
- [ ] 独自の造語や比喩表現を含まず、デザインパターンとして平易に説明されている
- [ ] `tests/unit/` に外部通信なしの決定論的テストが追加されている
- [ ] `tests/integration/test_patterns.py` に統合テストが追加されている
- [ ] `.venv/bin/ruff check .` と `.venv/bin/mypy shared/ production_patterns/` がパスする
- [ ] `.venv/bin/pytest tests/unit/ -v` が全件パスする
