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
