"""Coordinator Pattern - カスタマーサポートルーターエージェント。

パターンの特徴:
    Coordinator (LLM) が入力を分析し、適切な専門エージェントに動的に委譲する。
    Sequential/Parallel との違いは「LLM がルーティングを決定する」点。

    LLM ルーティングのため:
    - 柔軟な対応が可能（事前にルールを全列挙不要）
    - コストは高め（ルーティングにもモデル呼び出しが発生）
    - 予測不能な入力にも対応できる
"""

import sys
from pathlib import Path

from google.adk.agents import LlmAgent

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.config import get_settings

settings = get_settings()


def check_order_status(order_id: str) -> dict[str, str]:
    """注文状況を確認します。

    Args:
        order_id: 注文番号（例: ORD-12345）

    Returns:
        注文状況の詳細
    """
    # デモ用モックデータ
    mock_orders = {
        "ORD-001": {"status": "配送中", "estimated_delivery": "2024-01-20", "carrier": "ヤマト運輸"},
        "ORD-002": {"status": "処理中", "estimated_delivery": "2024-01-22", "carrier": "未確定"},
        "ORD-003": {"status": "配送完了", "delivered_date": "2024-01-15", "carrier": "佐川急便"},
    }
    order = mock_orders.get(order_id, {"status": "見つかりません", "note": f"{order_id} は存在しないか、アクセス権限がありません"})
    return {"order_id": order_id, **order}


def process_return_request(order_id: str, reason: str) -> dict[str, str]:
    """返品リクエストを処理します。

    Args:
        order_id: 返品する注文番号
        reason: 返品理由

    Returns:
        返品受付の結果
    """
    # デモ用: 購入から30日以内は返品可能
    return {
        "order_id": order_id,
        "return_status": "受付完了",
        "return_number": f"RET-{order_id}-001",
        "reason": reason,
        "instructions": "同梱の着払い伝票を使用してください。返金は受取確認から3〜5営業日です。",
    }


def process_refund(order_id: str, amount: int, reason: str) -> dict[str, str]:
    """返金を処理します。

    Args:
        order_id: 返金対象の注文番号
        amount: 返金金額（円）
        reason: 返金理由

    Returns:
        返金処理の結果
    """
    return {
        "order_id": order_id,
        "refund_status": "処理中",
        "refund_amount": f"¥{amount:,}",
        "reason": reason,
        "processing_time": "3〜5営業日でご指定の口座に振り込みます",
    }


def get_product_info(product_name: str) -> dict[str, str]:
    """商品情報を取得します。

    Args:
        product_name: 商品名またはカテゴリ

    Returns:
        商品情報
    """
    return {
        "product": product_name,
        "availability": "在庫あり",
        "price_range": "¥5,000〜¥50,000",
        "note": "詳細はウェブサイトをご確認ください",
    }


# =====================================================
# 専門エージェント（各ドメインのスペシャリスト）
# =====================================================
# description が重要！Coordinator の LLM がこの説明を読んで
# 「どのエージェントに委譲すべきか」を判断する
# =====================================================

order_agent = LlmAgent(
    name="order_specialist",
    model=settings.default_model,
    description="注文状況の確認、配送追跡に特化したエージェント。注文番号に関する問い合わせはすべてここへ。",
    instruction="""
あなたは注文管理の専門スタッフです。
顧客の注文状況の問い合わせに対して、check_order_status ツールで情報を確認し、
丁寧かつ迅速に回答してください。

注文番号が不明な場合は、確認方法をお伝えください。
""",
    tools=[check_order_status],
)

return_agent = LlmAgent(
    name="return_specialist",
    model=settings.default_model,
    description="返品・交換の手続きに特化したエージェント。商品が届かない、壊れていた、サイズが合わないなどの返品対応。",
    instruction="""
あなたは返品・交換担当のスタッフです。
お客様の返品リクエストを受け付け、process_return_request ツールで手続きを進めてください。

返品ポリシー: 商品受取から30日以内、未使用品のみ対応可能。
""",
    tools=[process_return_request],
)

refund_agent = LlmAgent(
    name="refund_specialist",
    model=settings.default_model,
    description="返金処理に特化したエージェント。支払い済みの取り消し、過剰請求の修正など金銭的な問題を担当。",
    instruction="""
あなたは経理・返金担当のスタッフです。
お客様の返金リクエストを受け付け、process_refund ツールで処理を進めてください。

返金の対象: 商品未着、重複請求、注文キャンセルなど。
""",
    tools=[process_refund],
)

product_agent = LlmAgent(
    name="product_specialist",
    model=settings.default_model,
    description="商品情報・在庫確認・製品の推薦に特化したエージェント。購入前の質問、商品比較、在庫確認はここへ。",
    instruction="""
あなたは商品アドバイザーです。
お客様の商品に関する質問に対して、get_product_info ツールで情報を取得し、
適切な商品の提案や情報提供を行ってください。
""",
    tools=[get_product_info],
)

# =====================================================
# Coordinator (LLM がダイナミックにルーティング)
# =====================================================
# sub_agents に専門エージェントを登録
# LLM がユーザーの意図を解釈して適切なエージェントに委譲
# =====================================================
root_agent = LlmAgent(
    name="customer_service_coordinator",
    model=settings.default_model,
    description="カスタマーサポートのコーディネーター。全ての問い合わせを受け付け、適切な専門スタッフに振り分ける。",
    instruction="""
あなたはカスタマーサポートのコーディネーターです。
お客様からの問い合わせを受け付け、内容を理解して最適な専門スタッフに委譲してください。

## 委譲ルール（柔軟に判断してください）
- 注文番号・配送状況の確認 → order_specialist
- 返品・交換の手続き → return_specialist
- 返金・過剰請求の修正 → refund_specialist
- 商品情報・在庫・購入前質問 → product_specialist
- 複数の問題が含まれる場合 → 最も重要な問題を担当するエージェントへ

## 注意事項
- 自分では問題を解決しようとせず、必ず専門エージェントに委譲してください
- お客様への挨拶と問い合わせ内容の確認のみ自分で行い、解決は専門家に任せてください
""",
    sub_agents=[
        order_agent,
        return_agent,
        refund_agent,
        product_agent,
    ],
)
