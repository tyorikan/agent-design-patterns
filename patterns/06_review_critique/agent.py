"""Review & Critique Pattern - ブログ記事 Generator/Critic ループ。

パターンの特徴:
    Loop Pattern の特殊形。Generator と Critic の2エージェントが
    コンテンツの品質が基準を満たすまで繰り返す。

    Loop (Lv.5) との違い:
    - Loop: 同一タスクを繰り返す汎用ループ
    - Review & Critique: Generator(生成) + Critic(批評) の役割分担が明確
"""

import sys
from pathlib import Path

from google.adk.agents import LlmAgent, LoopAgent

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.config import get_settings

settings = get_settings()

# =====================================================
# Generator: コンテンツ生成エージェント
# =====================================================
generator = LlmAgent(
    name="blog_generator",
    model=settings.default_model,
    description="ブログ記事を生成・改善する",
    instruction="""
あなたはプロのテクニカルライターです。

## タスク
ユーザーが指定したテーマについての技術ブログ記事を書いてください。

## 記事の要件
- 対象読者: クラウドエンジニア（初中級）
- 文字数: 600〜800文字
- 構成: タイトル、イントロ、本文（3セクション）、まとめ
- 技術的に正確であること
- 具体的なコード例や数値を含めること
- 読みやすい日本語で書くこと

記事の本文のみを出力してください。
""",
    output_key="article_draft",
)

# =====================================================
# Critic: 批評エージェント
# =====================================================
critic = LlmAgent(
    name="blog_critic",
    model=settings.default_model,
    description="ブログ記事を批評・改善提案する",
    instruction="""
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
スコアが 80 以上なら: [APPROVED] - 公開可能です
スコアが 80 未満なら: [NEEDS_REVISION] - 上記の点を改善してください
""",
    output_key="critic_feedback",
)

# =====================================================
# Review & Critique ループ
# =====================================================
root_agent = LoopAgent(
    name="blog_review_loop",
    description="Generator と Critic がコンテンツ品質を保証するまで繰り返すレビューループ",
    sub_agents=[
        generator,  # 記事を生成・改善
        critic,     # 記事を批評
    ],
    max_iterations=4,  # 最大4回（= 4サイクルの生成+批評）
)
