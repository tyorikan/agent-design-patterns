"""Single Agent デモ - GCP Q&A シナリオを自動実行。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agent import root_agent
from shared.demo_runner import run_demo

DEMO_QUERIES = [
    "Cloud Run と Cloud Functions の違いを教えてください。どちらを選ぶべきですか？",
    "Vertex AI で Gemini 3.5 Flash を使う最小限のPythonコードを教えてください",
    "Spanner と BigQuery の使い分けを教えてください",
]

if __name__ == "__main__":
    print("=" * 60)
    print("Lv.1 Single Agent パターン - GCP ドキュメント Q&A")
    print("=" * 60)
    print("1つの LlmAgent が google_search を使って自律的に回答します")
    print()

    run_demo(
        agent=root_agent,
        app_name="gcp_docs_agent",
        queries=DEMO_QUERIES,
    )
