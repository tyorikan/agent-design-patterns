#!/usr/bin/env python3
"""CI 品質ゲートスクリプト（`agents-cli eval grade` の結果を閾値判定して終了コードを制御）。

背景:
    `google-agents-cli` v1.12.0 の `agents-cli eval run` / `eval grade` は、
    採点スコアが 0 点であっても終了コード 0 を返す仕様となっている。
    CI/CD（GitHub Actions や Cloud Build）で品質劣化時にデプロイを確実にブロックするには、
    出力された `artifacts/grade_results/results_*.json` の `summary_metrics` を読み取り、
    閾値未満のメトリクスが 1 つでもあれば非ゼロ終了（exit 1）させるゲート層が必要になる。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

DEFAULT_THRESHOLDS: dict[str, float] = {
    "custom_response_quality": 4.0,
    "non_empty_structured_answer": 1.0,
    "agent_turn_count": 1.0,
}


def extract_mean_scores(grade_payload: dict[str, Any]) -> dict[str, float]:
    """`agents-cli eval grade` が出力した JSON からメトリクス別の平均スコアを抽出する。"""
    scores: dict[str, float] = {}
    summary_list = grade_payload.get("summary_metrics")
    if isinstance(summary_list, list):
        for item in summary_list:
            if not isinstance(item, dict):
                continue
            name = item.get("metric_name") or item.get("name")
            mean = item.get("mean_score")
            if isinstance(name, str) and isinstance(mean, int | float):
                scores[name] = float(mean)
    elif isinstance(summary_list, dict):
        for name, val in summary_list.items():
            if isinstance(val, int | float):
                scores[name] = float(val)
            elif isinstance(val, dict) and isinstance(val.get("mean_score"), int | float):
                scores[name] = float(val["mean_score"])
    return scores


def evaluate_gate(
    scores: dict[str, float],
    thresholds: dict[str, float] | None = None,
) -> tuple[bool, list[str]]:
    """メトリクス平均値を閾値辞書と照合し、(合否, 判定メッセージ一覧) を返す。"""
    active_thresholds = thresholds if thresholds is not None else DEFAULT_THRESHOLDS
    messages: list[str] = []
    passed = True

    for metric, min_score in active_thresholds.items():
        if metric not in scores:
            passed = False
            messages.append(f"[FAIL] {metric}: 結果に存在しません (required >= {min_score:.2f})")
            continue
        actual = scores[metric]
        if actual < min_score:
            passed = False
            messages.append(f"[FAIL] {metric}: {actual:.2f} < 閾値 {min_score:.2f}")
        else:
            messages.append(f"[PASS] {metric}: {actual:.2f} >= 閾値 {min_score:.2f}")

    return passed, messages


def find_latest_result_file(results_dir: Path) -> Path:
    """`artifacts/grade_results/` 配下の最新 `results_*.json` を返す。"""
    candidates = sorted(results_dir.glob("results_*.json"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        raise FileNotFoundError(f"採点結果 JSON が見つかりません: {results_dir}")
    return candidates[-1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="agents-cli eval grade 結果の CI 閾値ゲート")
    parser.add_argument(
        "--result-file",
        type=Path,
        default=None,
        help="判定対象の results_*.json パス（省略時は artifacts/grade_results の最新ファイル）",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=Path("artifacts/grade_results"),
        help="採点結果ディレクトリ",
    )
    args = parser.parse_args(argv)

    target_file = args.result_file or find_latest_result_file(args.results_dir)
    payload = json.loads(target_file.read_text(encoding="utf-8"))
    scores = extract_mean_scores(payload)
    passed, report_lines = evaluate_gate(scores)

    print(f"=== CI Quality Gate ({target_file}) ===")
    for line in report_lines:
        print(f"  {line}")

    if not passed:
        print("Result: BLOCKED (1 つ以上の評価指標がリリース基準を下回りました)", file=sys.stderr)
        return 1

    print("Result: PASSED (すべての評価指標がリリース基準を満たしました)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
