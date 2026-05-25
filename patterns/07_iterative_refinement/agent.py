"""Iterative Refinement Pattern - 自己改善型ドキュメント作成エージェント。

パターンの特徴:
    Review & Critique (Lv.6) との違い:
    - Lv.6: Generator（生成）+ Critic（批評）の2役割が別エージェント
    - Lv.7: 1エージェントが自己評価スコアを使って自律的に改善

    用途: スコアが閾値を超えるまで反復改善するコンテンツ生成
"""

import sys
from pathlib import Path

from google.adk.agents import LlmAgent, LoopAgent

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.config import get_settings

settings = get_settings()

# =====================================================
# ドキュメント改善エージェント（自己評価 + 改善）
# =====================================================
doc_refiner = LlmAgent(
    name="doc_refiner",
    model=settings.default_model,
    description="技術ドキュメントを自己評価しながら反復的に改善する",
    instruction="""
あなたは技術文書作成の専門家です。

## タスク: 技術ドキュメントの作成と改善

ユーザーが指定したテーマについて、技術ドキュメントを作成・改善してください。

---

## ドキュメント要件
- 対象読者: Google Cloud を学ぶエンジニア
- 構成: 概要、主要機能、ユースケース、始め方（コード例付き）、まとめ
- コードは Python または gcloud CLI を使用
- 図（ASCII アート）を含めること

## 自己評価（必須）

ドキュメントを作成後、以下の基準で自己採点してください:
- 技術的正確性 (30点): 内容の正確さ
- 網羅性 (25点): 重要な情報が含まれているか
- 読みやすさ (25点): 構成・文体・視覚的な見やすさ
- 実用性 (20点): コード例と実際の手順が使えるか

## 出力形式

---DOCUMENT---
[ドキュメント本文]
---SCORE---
総合スコア: XX/100
[各項目のスコアと理由]
判定: スコアが85以上なら [COMPLETE] 、未満なら [CONTINUE]
---END---
""",
    output_key="previous_doc_and_score",
)

# =====================================================
# Iterative Refinement ループ
# =====================================================
root_agent = LoopAgent(
    name="doc_refinement_loop",
    description="品質スコア 85 以上になるまで自己改善を繰り返す技術ドキュメント生成システム",
    sub_agents=[doc_refiner],
    max_iterations=5,
)
