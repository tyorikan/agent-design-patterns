"""Loop Pattern デモ - コード生成 & テストループ。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agent import root_agent
from shared.demo_runner import run_demo

TASK = """
以下の仕様で Python 関数を実装してください:

タスク: 二分探索 (Binary Search) の実装
- 関数名: binary_search
- 引数: sorted_list (ソート済みリスト), target (検索する値)
- 戻り値: target のインデックス（見つからない場合は -1）
- 型アノテーション必須
- docstring 必須
- エッジケース（空リスト、1要素）のテストケースをコメントで記載
"""

if __name__ == "__main__":
    print("=" * 60)
    print("Lv.5 Loop Pattern - コード生成 & テストループ")
    print("=" * 60)
    print("Code Generator と Code Tester が繰り返し実行されます:")
    print("  🔄 Loop 1: コード生成 → テスト")
    print("  🔄 Loop 2: 修正 → テスト（必要な場合）")
    print("  ✅ [APPROVED] が出たらループ終了（最大5回）")
    print()

    run_demo(
        agent=root_agent,
        app_name="code_generation_loop",
        queries=[TASK],
    )
