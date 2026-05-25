"""Sequential Pattern デモ - ETL パイプライン。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agent import root_agent
from shared.demo_runner import run_demo

# デモ用のサンプルデータ（CSVライクな生データ）
SAMPLE_RAW_DATA = """
以下の売上データを処理してください:

product_id,product_name,price,quantity,sale_date,category
P001,Cloud Run Pro,50000,3,2024-01-15,compute
P002,BigQuery Storage,120000,1,2024-01-15,analytics
P003,Spanner DB,,2,2024-01-16,database
P004,Pub/Sub Messaging,30000,5,2024-01-16,messaging
P001,Cloud Run Pro,50000,2,2024-01-17,compute
P005,Vertex AI Platform,200000,1,invalid-date,ai
P002,BigQuery Storage,120000,1,2024-01-17,analytics
P004,Pub/Sub Messaging,30000,3,2024-01-18,messaging
P006,GKE Enterprise,-5000,1,2024-01-18,compute

合計9レコード。price が空白のレコード、無効な日付のレコード、マイナス価格のレコードが含まれています。
"""

if __name__ == "__main__":
    print("=" * 60)
    print("Lv.3 Sequential Pattern - ETL データパイプライン")
    print("=" * 60)
    print("4つのエージェントが順番に実行されます:")
    print("  1. Extractor  → データ抽出")
    print("  2. Validator  → 品質チェック")
    print("  3. Transformer → データ変換")
    print("  4. Summarizer → 最終レポート")
    print()

    run_demo(
        agent=root_agent,
        app_name="etl_pipeline",
        queries=[SAMPLE_RAW_DATA],
    )
