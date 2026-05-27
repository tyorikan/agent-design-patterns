---
name: agentic-pipeline
description: |
  BaseAgent (PGEOrchestrator) + Antigravity Agent による Planner-Generator-Evaluator (PGE)
  3者間自律コード実装パイプラインの設計・実装スキル。
  BaseAgent でループ制御を管理し、各ノードの内部処理を Antigravity Agent に委任する
  ハイブリッドアーキテクチャの実装ガイド。
---

# Agentic Pipeline スキル

## 適用場面

以下のいずれかに該当する場合にこのスキルを使用すること:

- PGE（Planner-Generator-Evaluator）3者間ループを実装したい
- BaseAgent でループ制御しつつ、各ノードに自律エージェントを使いたい
- コード生成後に実際のツール（pytest, ruff 等）で検証したい
- REVISE 条件（スコア閾値、最大反復、リグレッションガード、改善停滞検出、ブロッカー判定）を設計したい

## アーキテクチャ

### レイヤー構造

```
PGEOrchestrator (BaseAgent — ループ制御)
├── run_planner_agent()   → Antigravity Agent
├── run_generator_agent() → Antigravity Agent
└── run_evaluator_agent() → Antigravity Agent
```

> ADK Workflow の条件付きエッジは ADK v2 に実装されているが、PGE パイプラインの複雑な
> ループ制御（スコア履歴管理、リグレッションガード、改善停滞検出、ブロッカー判定など）
> には不十分だったため、BaseAgent を採用した。

### 設計原則

1. **制御と実行の分離**: BaseAgent (PGEOrchestrator) = ループ制御、Antigravity = 実行エンジン
2. **自律性の委任**: 各 Antigravity Agent がビルトインツールで自律的に行動
3. **Structured Output**: Pydantic スキーマでノード間データを型保証
4. **動的 instruction**: callable instruction で初回/再設計を分岐
5. **スコア履歴管理**: `state["score_history"]` で改善停滞・リグレッションを検出
6. **ブロッカー検出**: Critical/High 課題が残存すればスコアに関わらず REVISE

### `_StateProxy` パターン

BaseAgent の `_run_async_impl()` 内では `ToolContext` が直接利用できないため、
`_StateProxy(state)` で `tool_context.state` アクセスを模倣する:

```python
class _StateProxy:
    """ToolContext の最小限の代替。state 辞書へのアクセスを提供する。"""
    def __init__(self, state: dict):
        self.state = state

async def _run_async_impl(self, ctx: InvocationContext):
    state = ctx.session.state
    tool_context = _StateProxy(state)
    plan = await run_planner_agent(user_request=..., tool_context=tool_context)
```

## Antigravity Agent のツール設定

### ビルトインツールの使い分け

| エージェント | ツール | policies |
|------------|-------|----------|
| Planner | `view_file`, `list_dir`, `search_dir` | デフォルト（run_command deny） |
| Generator | `create_file`, `edit_file`, `view_file`, `run_command` | `allow_commands=True`（ruff/pytest セルフチェック用） |
| Evaluator | `run_command`, `view_file` | `allow_commands=True`、`allow_writes=False` |

### ポリシー設定パターン

```python
from google.antigravity import Agent, CapabilitiesConfig, LocalAgentConfig
from google.antigravity.hooks import policy

# _build_config() で allow_commands=True を指定すると
# pytest / ruff check のみ実行を許可するポリシーが自動構築される
# （--fix は禁止: 修正は Generator 自身が edit_file で行う責務）

# Generator: ファイル書き込み可、セルフチェック用にコマンド実行可
generator_config = _build_config(
    system_instructions=GENERATOR_SYSTEM_PROMPT,
    response_schema=ArtifactOutput,
    allow_commands=True,   # ruff check / pytest を自律実行して品質を自己検証
    workspace_dir=output_dir,
)

# Evaluator: pytest/ruff のみ実行可、ファイル書き込み不可
evaluator_config = _build_config(
    system_instructions=system_prompt,
    response_schema=EvaluationOutput,
    allow_commands=True,
    allow_writes=False,    # Evaluator は評価のみ。コード修正は Generator の責務。
    workspace_dir=output_dir,
)
```

### Generator セルフチェック

Generator は `allow_commands=True` により、コード生成後に以下のセルフチェックサイクルを自律的に実行する:

```
コード生成 → ruff check → 修正 → pytest → 修正 → submit
```

これにより Evaluator に渡す前の品質を底上げし、PGE ループの反復回数を削減する。

### dynamic output_dir

`_resolve_output_dir(tool_context)` で `state["output_dir"]` から出力ディレクトリを動的に解決する:

```python
def _resolve_output_dir(tool_context: ToolContext) -> Path:
    output_dir_str = tool_context.state.get("output_dir", "")
    if output_dir_str:
        p = Path(output_dir_str).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p
    return DEFAULT_OUTPUT_DIR
```

未指定の場合は `patterns/agentic_pipeline/output/` がデフォルト。

## REVISE 条件の設計指針

### 6段階の終了判定（優先度順）

```
1. iteration >= max_iterations                → 強制 APPROVED（最大反復到達）
2. CRITICAL/HIGH ブロッカー残存               → 強制 REVISE（スコアに関わらず修正）
3. リグレッション（前回比スコア低下）          → 強制 REVISE
4. score < approval_threshold で LLM が APPROVED → 強制 REVISE
5. 改善停滞（改善幅 < min_improvement）         → APPROVED（条件付き承認）
6. LLM verdict をそのまま使用
```

### 推奨パラメータ

| パラメータ | 推奨値 | 根拠 |
|-----------|-------|------|
| approval_threshold | 80 | 品質基準の下限 |
| max_iterations | 3-5 | PGE 研究で3回で十分な収束 |
| min_improvement | 5 | これ以下は Diminishing Returns |

### スコア評価基準（0-100）

| 軸 | 配点 | 評価方法 |
|----|------|---------|
| テスト合格率 | 35 | pytest 実行結果 |
| コード品質 | 25 | ruff エラー・警告数 |
| 設計品質 | 20 | モジュール分離、責務の明確さ |
| テストカバレッジ | 20 | テストの網羅性 |

## Severity モデル

```python
class Severity(str, Enum):
    CRITICAL = "CRITICAL"  # 必ず修正（テスト失敗、セキュリティ脆弱性）
    HIGH = "HIGH"          # 修正推奨（エラーハンドリング不足、型不整合）
    MEDIUM = "MEDIUM"      # 改善推奨（命名、ドキュメント不足）
    LOW = "LOW"            # Nice to have（コードスタイル等）
```

## 認証

GEMINI_API_KEY を使用（Antigravity local harness に必須）:

`.env` に以下を設定:

```
GEMINI_API_KEY=your-api-key
```

## ユースケースカタログ

| ユースケース | Planner | Generator | Evaluator |
|------------|---------|-----------|-----------|
| **REST API 実装** | API 設計者 | バックエンドエンジニア | QA（pytest + ruff） |
| **CLI ツール実装** | 要件設計者 | CLI エンジニア | QA（pytest + ruff） |
| **データ処理** | パイプライン設計者 | データエンジニア | QA（pytest + ruff） |
| **ライブラリ開発** | API デザイナー | ライブラリエンジニア | QA（pytest + ruff） |

## アンチパターン

1. **Generator のセルフチェックを禁止しない**: `allow_commands=True` でセルフチェックを許可することで Evaluator 到達前の品質を底上げする
2. **REVISE 条件がないと無限ループ**: max_iterations は必ず設定する
3. **Structured Output なしだと不安定**: 自律エージェントの出力は型保証すべき
4. **スコア履歴を管理しないと改善停滞・リグレッションを検出できない**
5. **Critical/High ブロッカーチェックを省略しない**: スコアだけでは品質を保証できない
