"""Loop Pattern - コード生成 & テスト自動修正ループ（Workflow v2）。

パターンの特徴:
    ADK 2.x の `Workflow` 条件付きサイクルと決定論的ルーター `@node` を組み合わせ、
    「コード生成 → テスト評価 → 不合格なら改善再生成」を最大 `MAX_ITERATIONS` 回まで繰り返す。

⚠️ ADK 2.x における条件付きサイクルの重要ポイント:
    - `LlmAgent` 単体は `Event(route=...)` を発行しないため、`LlmAgent` の直後に直接
      `{"REVISE": ...}` を置いても `route=None` となりループは 1 回で終了してしまう。
    - 必ず判定用の関数ノード（`@node`）を挟み、評価テキストと反復回数上限（`MAX_ITERATIONS`）を
      検査して `Event(output=..., route="REVISE", state={...})` を明示返却する。
    - 2 周目以降に前回の評価フィードバック（`test_feedback`）を反映できるよう、
      `code_generator` の `instruction` は `ReadonlyContext` を受け取る関数にする。
"""

import sys
from pathlib import Path
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.agents.context import Context
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.events.event import Event
from google.adk.workflow import Workflow, node
from google.genai import types

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.config import get_settings

settings = get_settings()

MAX_ITERATIONS = 5


def _extract_text(value: Any) -> str:
    """ノード入力（`str` または `types.Content`）からプレーンテキストを抽出する。"""
    if isinstance(value, str):
        return value
    if isinstance(value, types.Content) and value.parts:
        return "".join(
            p.text for p in value.parts if p.text and not getattr(p, "thought", False)
        )
    return str(value or "")


async def _build_code_generator_instruction(ctx: ReadonlyContext) -> str:
    """初回は新規実装、2 周目以降は前回のテスト指摘を踏まえた修正プロンプトを構築する。"""
    prev_code = ctx.state.get("generated_code", "")
    feedback = ctx.state.get("test_feedback", "")

    revision_section = ""
    if feedback:
        revision_section = f"""
## 前回のコード
{prev_code}

## 前回のテスト評価フィードバック（必ずすべて解消してください）
{feedback}
"""

    return f"""\
あなたは熟練した Python エンジニアです。

## タスク
ユーザーが依頼した内容を実装する Python 関数を書いてください。
{revision_section}
## 要件
- 型アノテーションを使うこと
- docstring を書くこと
- エラーハンドリングを含めること
- テスト可能なコードにすること

## 出力形式
```python
[完全な Python コードのみ。説明文は最小限に]
```

コードブロックの中にのみ実行可能なコードを書いてください。
"""


# =====================================================
# Step 1: コード生成エージェント
# =====================================================
code_generator = LlmAgent(
    name="code_generator",
    model=settings.default_model,
    description="Python 関数のコードを生成・改善する",
    instruction=_build_code_generator_instruction,
    output_key="generated_code",
)

# =====================================================
# Step 2: コードテスト・評価エージェント
# =====================================================
code_tester = LlmAgent(
    name="code_tester",
    model=settings.default_model,
    description="生成されたコードをテスト・評価する",
    instruction="""\
あなたは QA エンジニアです。以下のコードを厳格に評価してください。

## 評価対象コード
{generated_code}

## 評価基準
1. **正確性**: ユーザーの要件を満たしているか
2. **型アノテーション**: 正しく使われているか
3. **エラーハンドリング**: 適切な例外処理があるか
4. **コード品質**: 可読性、命名、docstring
5. **テスト可能性**: 単体テストが書けるか

## 出力形式

### 評価結果
- スコア: X/100
- ステータス: [APPROVED] または [NEEDS_REVISION]

### 発見した問題
（問題のリスト、またはなければ「問題なし」）

### 改善提案
（次の反復での改善点）

⚠️ 重要:
- スコアが 80 以上なら必ず `[APPROVED]` と記載してください。
- スコアが 80 未満なら必ず `[NEEDS_REVISION]` と記載してください。
""",
    output_key="test_feedback",
)


# =====================================================
# Step 3: 決定論的ループルーター（@node）
# =====================================================
@node(name="loop_router")
def loop_router(ctx: Context, node_input: Any) -> Event:
    """`code_tester` の判定結果と反復上限を検査し、`REVISE` または `APPROVED` へ分岐する。"""
    iteration = int(ctx.state.get("loop_iteration", 0)) + 1
    feedback = _extract_text(node_input) or str(ctx.state.get("test_feedback", ""))
    upper = feedback.upper()

    is_approved = "[APPROVED]" in upper
    needs_revision = ("[NEEDS_REVISION]" in upper or "REVISE" in upper) and not is_approved

    if needs_revision and iteration < MAX_ITERATIONS:
        return Event(
            output=feedback,
            route="REVISE",
            state={"loop_iteration": iteration, "test_feedback": feedback},
        )
    return Event(
        output=str(ctx.state.get("generated_code", feedback)),
        route="APPROVED",
        state={"loop_iteration": iteration, "test_feedback": feedback},
    )


@node(name="finalize_code")
def finalize_code(ctx: Context, node_input: Any) -> str:
    """承認済み（または上限到達時）の最終コードをワークフロー出力として返す。"""
    return str(ctx.state.get("generated_code") or _extract_text(node_input))


# =====================================================
# Workflow（条件付きサイクル + 最大反復回数ガード）
# =====================================================
root_agent = Workflow(
    name="code_generation_loop",
    description="コード生成とテストを品質が担保されるまで繰り返すループ",
    edges=[
        (
            "START",
            code_generator,
            code_tester,
            loop_router,
            {"REVISE": code_generator, "APPROVED": finalize_code},
        ),
    ],
)
