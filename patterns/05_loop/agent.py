"""Loop Pattern - コード生成 & テスト自動修正ループ（修正版）。

パターンの特徴:
    LoopAgent が sub_agents を終了条件を満たすまで繰り返す。
    今回は「コード生成 → テスト → 失敗なら修正」をループする。

    重要: max_iterations で必ず上限を設定する！

ADK の {変数名} の注意点:
    - LoopAgent の最初のイテレーション開始時、セッション状態は空
    - 最初に実行される code_generator は {変数} を使わない
    - code_tester は code_generator の output_key={generated_code} を参照できる
"""

import sys
from pathlib import Path

from google.adk.agents import LlmAgent, LoopAgent

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.config import get_settings

settings = get_settings()

# =====================================================
# Step 1: コード生成エージェント
# ⚠️ 最初のエージェント: {変数} は使わない
#    ユーザーメッセージから直接タスクを読み取る
# =====================================================
code_generator = LlmAgent(
    name="code_generator",
    model=settings.default_model,
    description="Python 関数のコードを生成・改善する",
    instruction="""
あなたは熟練した Python エンジニアです。

## タスク
ユーザーが依頼した内容を実装する Python 関数を書いてください。

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
""",
    output_key="generated_code",
)

# =====================================================
# Step 2: コードテスト・評価エージェント
# ★ code_generator の output_key={generated_code} を参照できる
# =====================================================
code_tester = LlmAgent(
    name="code_tester",
    model=settings.default_model,
    description="生成されたコードをテスト・評価する",
    instruction="""
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

⚠️ 重要: スコアが 80 以上なら必ず [APPROVED] と記載してください。
""",
    output_key="test_feedback",
)

# =====================================================
# Loop Agent の定義
# =====================================================
# LoopAgent = 終了条件を満たすまで sub_agents を繰り返す
#
# 終了方法:
#   1. max_iterations に達した場合（強制終了）
#   2. エージェントが escalate アクションを実行した場合
# =====================================================
root_agent = LoopAgent(
    name="code_generation_loop",
    description="コード生成とテストを品質が担保されるまで繰り返すループ",
    sub_agents=[
        code_generator,  # コードを生成（ユーザーメッセージから）
        code_tester,     # コードをテスト・評価 ({generated_code} を参照)
    ],
    max_iterations=5,  # ⚠️ 無限ループ防止: 最大5回まで
)
