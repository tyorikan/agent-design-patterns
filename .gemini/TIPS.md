# TIPS - 開発で得られた知見

## ADK v2 移行の知見（2026-05-25）

### Workflow の namespace
- ❌ `google.adk.workflows` は存在しない
- ✅ `google.adk.workflow` が正しい namespace
- `from google.adk.workflow import Workflow`

### Workflow の edges 構文

| パターン | 構文 | 例 |
|----------|------|-----|
| Sequential | チェーンタプル | `("START", a, b, c)` |
| Parallel | ネストタプル | `("START", (a, b), aggregator)` |
| Loop | 条件付きサイクル | `("START", a, b, {"REVISE": a})` |

### 無条件サイクルは禁止
```python
# ❌ ValidationError: Unconditional cycle detected
edges=[("START", a, b, (b, a))]

# ✅ 条件付きエッジで定義
edges=[("START", a, b, {"REVISE": a})]
```

### Workflow は BaseAgent ではなく BaseNode のサブクラス
```python
# ❌ ValidationError
root_agent = LlmAgent(sub_agents=[Workflow(...)])

# ✅ Workflow の edges に組み込む
root_agent = Workflow(edges=[
    ("START", coordinator, (parallel_a, parallel_b), ...),
])
```

### uv sync の staging index 問題
- gcloud 由来の staging index URL が `uv lock/sync` に影響
- `uv pip install --index-url https://pypi.org/simple/` で回避可能

### Workflow の max_iterations
- v1 の `LoopAgent(max_iterations=N)` は v2 では使えない
- 代わりに LlmAgent の instruction で品質スコア閾値を明確にし、条件付きエッジで制御
- 無限ループのリスクがあるため、instruction での閾値設定が重要

### output_key は Workflow でも有効
- `LlmAgent(output_key="result")` はそのまま動作
- Workflow のノード間データ受け渡しに `{variable_name}` 構文が使える
- 並列実行されるエージェントには異なる output_key を使うこと

## Agentic Pipeline（PGE パイプライン）の知見（2026-05-27）

### Antigravity SDK の `LocalAgentConfig` 設定パターン
```python
config = LocalAgentConfig(
    system_instructions="...",
    response_schema=EvalResult,       # Pydantic モデルで構造化出力
    policies=AgentPolicies(
        allow_writes=True,            # ファイル書き込み許可
        allow_commands=True,          # コマンド実行許可
    ),
    capabilities=AgentCapabilities(
        code_execution=True,
    ),
    workspaces=[AgentWorkspace(
        root=output_dir,
        read_only=False,
    )],
)
```
- `response_schema` に Pydantic モデルを渡すと JSON 構造化出力が強制される
- `allow_commands=True` で ruff/pytest のセルフチェックが可能に

### `_StateProxy` パターン
- BaseAgent 内では ToolContext が使えないため、`session.state` へのアクセスを模倣する辞書ラッパー
- `InvocationContext.session.state` を直接読み書きし、ToolContext の `state["key"]` と同じインターフェースを提供

### Generator の ruff セルフチェック
- `allow_commands=True` + プロンプトで `ruff check .` → 修正 → `pytest` → 修正 → submit を指示
- ❌ `ruff check --fix` は使用禁止
- ✅ 手動修正を強制する理由: LLM が修正意図を理解してコード品質を向上させるため

### Evaluator の `allow_writes=False`
- Evaluator はコードを修正してはならない（評価のみ）
- コード修正の責務は Generator に集約（責務分離）

### `score_history` による改善停滞検出
- 各イテレーションの Evaluator スコアを `score_history` リストに記録
- 前回比改善幅 < `min_improvement` の場合、LLM verdict に関わらず APPROVED に変更
- これ以上の反復は品質向上に寄与しないと判断して早期終了

### リグレッションガード
- 前回比でスコアが低下した場合、LLM が APPROVED と判定しても REVISE に強制上書き
- コード品質の後退を防止する安全弁

### 差分修正モード
- `score >= 60` の場合、既存設計を維持し指摘点のみ修正するようプロンプトで指示
- 全面的な再設計を禁止し、収束を促進

### 相対インポート
- `adk run` で実行するには、パッケージ内は相対インポート（`from .tools import ...`）を使う
- `__init__.py` でプロジェクトルートを `sys.path` に追加して `shared` パッケージを解決
```python
# patterns/agentic_pipeline/__init__.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
```
