"""Review & Critique Pattern - ブログ記事 Generator/Critic ループ（Workflow v2）。

パターンの特徴:
    Generator（執筆）と Critic（批評）の 2 つの専門 `LlmAgent` に加え、
    決定論的ルーター `@node` が品質判定と最大反復回数（`MAX_ITERATIONS`）を制御する。

    Loop (Lv.5) との違い:
    - Loop: テスト結果や終了条件に基づく汎用反復制御
    - Review & Critique: 生成者（Generator）と批評者（Critic）のペルソナ・評価軸を明確に分離
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

MAX_ITERATIONS = 4


def _extract_text(value: Any) -> str:
    """ノード入力からプレーンテキストを抽出する。"""
    if isinstance(value, str):
        return value
    if isinstance(value, types.Content) and value.parts:
        return "".join(
            p.text for p in value.parts if p.text and not getattr(p, "thought", False)
        )
    return str(value or "")


async def _build_blog_generator_instruction(ctx: ReadonlyContext) -> str:
    """初回は新規執筆、2 周目以降は Critic の改善指示を反映するプロンプトを構築する。"""
    prev_draft = ctx.state.get("article_draft", "")
    feedback = ctx.state.get("critic_feedback", "")

    revision_section = ""
    if feedback:
        revision_section = f"""
## 前回のドラフト
{prev_draft}

## 編集者（Critic）からの改善指示（すべて反映して改稿してください）
{feedback}
"""

    return f"""\
あなたはプロのテクニカルライターです。

## タスク
ユーザーが指定したテーマについての技術ブログ記事を書いてください。
{revision_section}
## 記事の要件
- 対象読者: クラウドエンジニア（初中級）
- 文字数: 600〜800文字
- 構成: タイトル、イントロ、本文（3セクション）、まとめ
- 技術的に正確であること
- 具体的なコード例や数値を含めること
- 読みやすい日本語で書くこと

記事の本文のみを出力してください。
"""


# =====================================================
# Generator: コンテンツ生成エージェント
# =====================================================
generator = LlmAgent(
    name="blog_generator",
    model=settings.default_model,
    description="ブログ記事を生成・改善する",
    instruction=_build_blog_generator_instruction,
    output_key="article_draft",
)

# =====================================================
# Critic: 批評エージェント
# =====================================================
critic = LlmAgent(
    name="blog_critic",
    model=settings.default_model,
    description="ブログ記事を批評・改善提案する",
    instruction="""\
あなたは厳格な編集者です。以下のブログ記事を評価してください。

## 評価対象記事
{article_draft}

## 評価基準（各20点、合計100点）
1. **技術的正確性**: 内容に誤りはないか
2. **読みやすさ**: 構成、文章、流れは適切か
3. **具体性**: コード例・数値・事例があるか
4. **対象読者への適合**: 初中級エンジニアに合っているか
5. **実用性**: 読者がすぐに使える情報があるか

## 出力形式

### 評価スコア
- 総合スコア: XX/100

### 優れている点
（3点以内）

### 改善が必要な点
（具体的な改善指示を3点以内）

### 最終判定
- スコアが 80 以上なら必ず `[APPROVED]` - 公開可能です と記載してください
- スコアが 80 未満なら必ず `[NEEDS_REVISION]` - 上記の点を改善してください と記載してください
""",
    output_key="critic_feedback",
)


# =====================================================
# 決定論的レビュールーター（@node）
# =====================================================
@node(name="review_router")
def review_router(ctx: Context, node_input: Any) -> Event:
    """`blog_critic` の判定結果と反復回数上限に基づき、`REVISE` または `APPROVED` を返す。"""
    iteration = int(ctx.state.get("review_iteration", 0)) + 1
    feedback = _extract_text(node_input) or str(ctx.state.get("critic_feedback", ""))
    upper = feedback.upper()

    is_approved = "[APPROVED]" in upper
    needs_revision = ("[NEEDS_REVISION]" in upper or "REVISE" in upper) and not is_approved

    if needs_revision and iteration < MAX_ITERATIONS:
        return Event(
            output=feedback,
            route="REVISE",
            state={"review_iteration": iteration, "critic_feedback": feedback},
        )
    return Event(
        output=str(ctx.state.get("article_draft", feedback)),
        route="APPROVED",
        state={"review_iteration": iteration, "critic_feedback": feedback},
    )


@node(name="finalize_article")
def finalize_article(ctx: Context, node_input: Any) -> str:
    """承認済み（または上限到達時）の記事本文を返す。"""
    return str(ctx.state.get("article_draft") or _extract_text(node_input))


# =====================================================
# Workflow（条件付きサイクル + 最大反復回数ガード）
# =====================================================
root_agent = Workflow(
    name="blog_review_loop",
    description="Generator と Critic がコンテンツ品質を保証するまで繰り返すレビューループ",
    edges=[
        (
            "START",
            generator,
            critic,
            review_router,
            {"REVISE": generator, "APPROVED": finalize_article},
        ),
    ],
)
