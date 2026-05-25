---
name: ai-agent-testing-strategy
description: |
  AI エージェントのテスト戦略スキル。
  非決定的な LLM 出力に対して「何をどう検証すべきか」の判断基準を提供する。
  テストピラミッドの設計、プロパティベース検証、トラジェクトリ検証の使い分け、
  パッケージ更新・リファクタリング時のリグレッション検出戦略を網羅する。
  テスト設計・テスト再構築・パッケージ更新・CI/CD 設計時に参照すること。
---

# AI エージェント テスト戦略スキル

## このスキルの目的

AI エージェントのテストを設計する際の **判断基準** を提供する。
具体的な ADK API の使い方は `adk-testing-debugging` スキルを参照すること。
このスキルは **「何を・なぜ・どう検証すべきか」** に焦点を当てる。

---

## 1. 基本原則: なぜ AI エージェントのテストは特殊か

### 従来ソフトウェア vs AI エージェント

| 観点 | 従来ソフトウェア | AI エージェント |
|------|-----------------|----------------|
| 出力 | 決定的 | **非決定的**（同じ入力でも毎回異なる） |
| 正解 | 1つ | **複数あり得る**（意味的に等価な表現が無数） |
| 失敗の定義 | 明確（例外、不正値） | **曖昧**（品質が低い、意図と違う） |
| テストの再現性 | 100% | **保証なし**（temperature, モデルバージョンに依存） |

### 根本的な設計方針

```
❌ 従来のアプローチ（不安定・脆い）
assert response == "Cloud Run はサーバーレスのコンテナ実行環境です"
assert "スコア" in response

✅ AI エージェント向けアプローチ（安定・堅牢）
assert len(response) > 100                    # プロパティ: 十分な出力がある
assert "order_specialist" in trajectory       # トラジェクトリ: 正しい経路を通った
assert isinstance(json.loads(response), dict) # 構造: パース可能な形式である
```

**鉄則: 出力の「内容」ではなく「性質」と「経路」を検証する。**

---

## 2. テストピラミッド

```
        ▲ コスト・不安定性（高）
       / \
      / Lv.4 \     E2E シミュレーション（マルチターン再生）
     /─────────\
    /   Lv.3    \  Eval スイート（LLM-as-a-Judge, Golden Dataset）
   /─────────────\
  /     Lv.2      \ 統合テスト（実 LLM、プロパティ + トラジェクトリ）
 /─────────────────\
/       Lv.1        \ ユニットテスト（LLM なし、構成の決定的検証）
/───────────────────────\
        ▼ 速度・信頼性（高）
```

### 各レベルの判断基準

| レベル | LLM 呼出 | 何を検証するか | いつ実行するか | 目安テスト数 |
|--------|---------|---------------|--------------|-------------|
| **Lv.1** | ❌ なし | エージェントの構成（型、名前、sub_agents、tools、output_key） | **毎コミット**、CI 必須 | 多（全エージェント × 3-5項目） |
| **Lv.2** | ✅ あり | 出力のプロパティ（長さ、構造）+ エージェントのトラジェクトリ | PR マージ前、定期実行 | 中（パターンごとに 1-2） |
| **Lv.3** | ✅ あり | 出力の品質（正確性、網羅性、トーン）をスコアリング | リリース前、週次 | 少（重要パターンのみ） |
| **Lv.4** | ✅ あり | マルチターン対話の一貫性、エラー回復能力 | リリース前 | 少（クリティカルフローのみ） |

### レベル選択の意思決定フロー

```
テストしたいものは何か？
  │
  ├─ エージェントの構成（型、名前、接続関係）が正しいか？
  │   └→ Lv.1（ユニットテスト）
  │
  ├─ エージェントが「動く」か？正しい経路を通るか？
  │   └→ Lv.2（統合テスト + トラジェクトリ）
  │
  ├─ 出力の「品質」は十分か？
  │   └→ Lv.3（Eval スイート）
  │
  └─ 複数ターンの対話で一貫性があるか？
      └→ Lv.4（E2E シミュレーション）
```

---

## 3. Lv.1 ユニットテスト: 構成の決定的検証

### 原則

- **LLM を一切呼ばない。** ミリ秒で完了する。
- エージェントの **グラフトポロジー** を検証する。
- パッケージ更新やリファクタリング時の **リグレッション検出の第一防衛線** 。

### 何を検証するか（チェックリスト）

| 検証項目 | テスト例 | なぜ重要か |
|----------|---------|-----------|
| エージェントの型 | `isinstance(agent, LlmAgent)` | 型が変わると動作が根本的に変わる |
| エージェントの名前 | `agent.name == "coordinator"` | ADK Web UI、ログ、トラジェクトリに影響 |
| sub_agents の数 | `len(agent.sub_agents) == 4` | エージェントの追加・削除を検出 |
| sub_agents の順序 | `names == ["a", "b", "c"]` | Sequential/Loop で順序が重要 |
| output_key の設定 | `agent.output_key == "result"` | パイプラインのデータ受け渡しが壊れる |
| tools の存在 | `len(agent.tools) > 0` | ツールがないと ReAct パターンが機能しない |
| max_iterations | `agent.max_iterations > 0` | LoopAgent の無限ループ防止 |

### モジュールローディングの注意点

```python
# ❌ 危険: sys.modules キャッシュが汚染される
from patterns.XX.agent import root_agent

# ✅ 安全: importlib.util で毎回独立にロード
import importlib.util

def load_pattern_agent(pattern_dir: str):
    agent_path = ROOT / "patterns" / pattern_dir / "agent.py"
    spec = importlib.util.spec_from_file_location(f"agent_{pattern_dir}", agent_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
```

**なぜ重要:** 複数パターンが同じ変数名（`root_agent`, `settings`）を使うため、
通常の `import` では `sys.modules` のキャッシュで別パターンのモジュールが返される。

---

## 4. Lv.2 統合テスト: プロパティベース + トラジェクトリ検証

### 原則

- **実際の LLM を呼ぶ。** エージェントが「動く」ことを検証する。
- 出力の **「内容」ではなく「性質」** を検証する（プロパティベース）。
- 最終出力だけでなく、**「どのエージェントが発言したか」** を検証する（トラジェクトリ）。

### 4.1 プロパティベーステスト

出力の **構造的特徴** を検証する。LLM がどんな文言で返しても PASS する。

| プロパティ | テスト例 | 適用場面 |
|-----------|---------|---------|
| 長さ | `len(response) > 200` | 全パターン |
| 構造 | `response.count("\n") > 5` | レポート生成系 |
| フォーマット | `json.loads(response)` | 構造化出力 |
| コード含有 | `"def " in response` | コード生成系 |
| 数値範囲 | `0 <= score <= 100` | スコアリング系 |

```python
# ✅ プロパティベーステスト
async def test_report_has_sufficient_content():
    response = await run_agent(agent, "app", "分析レポートを作成して")
    assert len(response) > 200, "レポートが短すぎます"
```

### 4.2 トラジェクトリ検証 ★重要

最終出力ではなく、エージェントの **行動経路** を検証する。
マルチエージェントシステムで最も効果的。

```python
# ✅ トラジェクトリ検証
async def test_coordinator_routes_correctly():
    response, trajectory = await run_agent_trajectory(agent, "app", query)

    # どのエージェントが発言したかを検証
    assert "order_specialist" in trajectory
    # 最終出力の内容は問わない
```

**なぜトラジェクトリ検証が強力か:**

| 検証対象 | キーワードテスト | プロパティテスト | トラジェクトリ検証 |
|----------|:---------------:|:---------------:|:-----------------:|
| LLM 出力に依存 | ✅ 強く依存 | 🟡 弱く依存 | ❌ 依存しない |
| 非決定性の影響 | 🔴 大 | 🟡 小 | 🟢 なし |
| 協調動作の検証 | ❌ 不可 | ❌ 不可 | ✅ 可能 |
| ルーティングの検証 | ❌ 不可 | ❌ 不可 | ✅ 可能 |

### 4.3 ADK の `is_final_response()` の注意点

```python
# ❌ 危険: LoopAgent/SequentialAgent では is_final_response() が True にならないことがある
async for event in runner.run_async(...):
    if event.is_final_response():  # ← LoopAgent で空になるリスク
        text += event.content.parts[0].text

# ✅ 安全: 全イベントからテキストを収集
async for event in runner.run_async(...):
    if event.content and event.content.parts:
        for part in event.content.parts:
            if hasattr(part, "text") and part.text:
                text += part.text
    if event.author:
        trajectory.append(event.author)  # トラジェクトリも同時に収集
```

**影響を受けるエージェントタイプ:**
- `LoopAgent` — ループ終了時に `is_final_response()` が True にならない場合がある
- `SequentialAgent`（内部に LoopAgent を含む場合）— 同上

**影響を受けないエージェントタイプ:**
- `LlmAgent`（単体）— 常に `is_final_response()` で取得可能
- Coordinator パターン（`LlmAgent` が root）— 同上

### 4.4 エージェントタイプ別テスト戦略

| エージェントタイプ | 推奨テスト方式 | 理由 |
|-------------------|--------------|------|
| `LlmAgent` 単体 | `run_agent_final_response()` | `is_final_response()` が確実 |
| `SequentialAgent` | `run_agent_trajectory()` | sub_agents の実行順序を検証 |
| `ParallelAgent` | `run_agent_trajectory()` | 全 researcher の参加を検証 |
| `LoopAgent` | `run_agent_trajectory()` | 全イベント収集 + 反復を検証 |
| Coordinator | `run_agent_trajectory()` | ルーティング先を検証 |
| Swarm | `run_agent_trajectory()` | 全専門家の参加 + consensus を検証 |

---

## 5. パッケージ更新・リファクタリング時のテスト戦略

### パッケージ更新時の判断フロー

```
パッケージ更新
  │
  ├─ 1. Lv.1 ユニットテストを実行（1秒）
  │   ├─ PASS → エージェント構成は壊れていない
  │   └─ FAIL → API の破壊的変更を検出（型名変更、引数変更など）
  │
  ├─ 2. Lv.2 統合テストを実行（10-20分）
  │   ├─ PASS → エージェントの動作は正常
  │   └─ FAIL → 動作の非互換性を検出
  │       ├─ トラジェクトリ FAIL → ルーティング/協調動作が壊れた
  │       └─ プロパティ FAIL → 出力品質が低下した
  │
  └─ 3. 全 PASS → 更新を適用
```

### 何をテストすべきか（更新シナリオ別）

| シナリオ | Lv.1 で検出 | Lv.2 で検出 | 追加対応 |
|----------|:-----------:|:-----------:|---------|
| ADK マイナーバージョン更新 | 型名変更、引数変更 | 動作の非互換性 | DeprecationWarning を確認 |
| ADK メジャーバージョン更新 | 構成 API の破壊的変更 | 全パターンの動作検証 | 移行ガイドを確認 |
| LLM モデル変更 | — | 出力品質の変化 | Lv.3 Eval で品質スコア比較 |
| Python バージョン更新 | — | — | 依存関係の互換性確認 |
| リファクタリング | sub_agents 構成の変更 | 動作の等価性 | Before/After で Lv.2 結果を比較 |

### DeprecationWarning の活用

```python
# pyproject.toml に追加して Deprecation を可視化
[tool.pytest.ini_options]
filterwarnings = [
    "default::DeprecationWarning",  # 警告を表示（無視しない）
]
```

**実例:** ADK の `SequentialAgent`, `ParallelAgent`, `LoopAgent` は
将来 `Workflow` に統合される DeprecationWarning が出ている。
Lv.1 テストがあれば、移行時に構成が壊れていないことを瞬時に確認できる。

---

## 6. テスト共通ヘルパーの設計

### conftest.py に集約すべきもの

| ヘルパー | 目的 | 使用レベル |
|---------|------|-----------|
| `load_pattern_agent(dir)` | モジュールキャッシュを回避してエージェントをロード | Lv.1, Lv.2 |
| `run_agent_final_response()` | `is_final_response()` のテキスト取得 | Lv.2（LlmAgent 単体） |
| `run_agent_all_text()` | 全イベントからテキスト収集 | Lv.2（LoopAgent 系） |
| `run_agent_trajectory()` | テキスト + 発言エージェント一覧 | Lv.2（マルチエージェント） |

### ヘルパー選択の判断基準

```
エージェントを実行してテストしたい
  │
  ├─ root_agent は LlmAgent 単体か？
  │   └→ run_agent_final_response() を使用
  │
  ├─ root_agent は LoopAgent / SequentialAgent（LoopAgent 含む）か？
  │   └→ run_agent_trajectory() を使用（全イベント収集 + トラジェクトリ）
  │
  └─ マルチエージェントのルーティングを検証したいか？
      └→ run_agent_trajectory() を使用（トラジェクトリでルーティング先を確認）
```

---

## 7. アンチパターン集

### ❌ キーワード完全一致

```python
# 悪い: LLM の表現に依存
assert "スコア: 85/100" in response
```

**問題:** LLM が「85点」「85/100点」「スコアは85」と表現を変えるだけで FAIL。

### ❌ is_final_response() への過度な依存

```python
# 悪い: LoopAgent で空レスポンスになるリスク
if event.is_final_response():
    response = event.content.parts[0].text
```

**問題:** `LoopAgent` では `is_final_response()` が一度も True にならないことがある。

### ❌ 分散テスト構造

```
# 悪い: 各パターンに tests/ を持つ
patterns/01/tests/test_agent.py
patterns/02/tests/test_agent.py  # 同名ファイルで sys.modules が汚染される
```

**問題:** `sys.modules` のキャッシュにより、別パターンのモジュールがロードされる。

### ❌ テスト間の状態共有

```python
# 悪い: テスト間でセッションを共有
session_service = InMemorySessionService()  # モジュールレベルで1つ

# 良い: 各テストで独立したセッションを作成
async def test_xxx():
    session_service = InMemorySessionService()  # テストごとに新規作成
```

---

## 8. チェックリスト: テスト設計レビュー

新しいエージェントのテストを設計する際、以下を確認する:

- [ ] Lv.1: エージェントの型・名前・sub_agents 構成が検証されているか
- [ ] Lv.1: output_key / max_iterations など重要な設定が検証されているか
- [ ] Lv.2: プロパティベーステスト（出力の長さ・構造）が書かれているか
- [ ] Lv.2: トラジェクトリ検証（正しいエージェントが発言したか）が書かれているか
- [ ] Lv.2: LoopAgent 系で `is_final_response()` に依存していないか
- [ ] ヘルパー: `importlib.util` でモジュールをロードしているか
- [ ] ヘルパー: 各テストで独立したセッションを作成しているか
- [ ] CI: Lv.1 が毎コミットで実行される設定か
- [ ] 非決定性: キーワード完全一致に依存していないか
- [ ] 非決定性: 失敗時のエラーメッセージに実際の値が含まれているか

---

## 参考リソース

- [Vertex AI Gen AI Evaluation](https://cloud.google.com/vertex-ai/generative-ai/docs/models/evaluation-overview)
- [ADK Evaluation](https://google.github.io/adk-docs/evaluate/)
- [DeepEval](https://github.com/confident-ai/deepeval) — OSS の LLM 評価フレームワーク
- [LangSmith](https://smith.langchain.com/) — トレーシング・評価プラットフォーム
- [pytest-rerunfailures](https://github.com/pytest-dev/pytest-rerunfailures) — 非決定的テストの自動リトライ
