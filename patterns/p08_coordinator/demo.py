"""Coordinator Pattern デモ - カスタマーサポートルーター。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from agent import root_agent
from shared.demo_runner import run_demo

QUERIES = [
    "注文番号 ORD-001 の配送状況を教えてください",
    "先週購入した商品を返品したいのですが、注文番号は ORD-002 です。商品に傷があります",
    "注文 ORD-003 の二重請求があったようで、返金をお願いしたいです。金額は 5000 円です",
    "Cloud Run の Enterprise プランについて詳しく教えてください",
]

if __name__ == "__main__":
    print("=" * 60)
    print("Lv.8 Coordinator Pattern - カスタマーサポートルーター")
    print("=" * 60)
    print("LLM がユーザーの意図を判断して適切な専門エージェントに振り分けます")
    print()
    run_demo(root_agent, "customer_service_coordinator", QUERIES)
