from __future__ import annotations

import difflib
import json
from collections import Counter
from pathlib import Path
from typing import Sequence

from openpyxl import Workbook

from optimizer.evaluation import EvaluationResult
from optimizer.scoring import aggregate_scores

SECRET_KEY_MARKERS = (
    "secret",
    "token",
    "authorization",
    "password",
    "credential",
    "salt",
    "api_key",
    "gateway_key",
    "base64",
    "raw_image",
    "image_bytes",
    "ssm_value",
)


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _sanitize(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if _is_secret_key(key) else _sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def _is_secret_key(key: object) -> bool:
    lowered = str(key).lower()
    return any(marker in lowered for marker in SECRET_KEY_MARKERS)


def _summary(phase: str, results: Sequence[EvaluationResult]) -> dict[str, object]:
    score = aggregate_scores(result.row_score for result in results)
    failures = Counter(result.failure_category for result in results if result.failure_category)
    return {
        "phase": phase,
        "samples": len(results),
        "business_total": score.business_total,
        "business_correct": score.business_correct,
        "business_accuracy": score.business_accuracy,
        "strict_correct": score.strict_correct,
        "strict_accuracy": score.strict_accuracy,
        "failure_categories": dict(sorted(failures.items())),
    }


def _write_results_xlsx(path: Path, results: Sequence[EvaluationResult]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "results"
    ws.append(
        [
            "row_number",
            "card_image",
            "origin",
            "expected",
            "actual",
            "business_correct",
            "business_total",
            "failure_category",
            "image_status",
        ]
    )
    for result in results:
        ws.append(
            [
                result.sample.row_number,
                result.sample.card_image,
                result.sample.origin,
                result.sample.expected_raw,
                "\n".join(result.actual_numbers),
                result.row_score.business_correct,
                result.row_score.business_total,
                result.failure_category,
                result.image_status,
            ]
        )
    wb.save(path)


def write_run_artifacts(
    run_dir: Path,
    phase: str,
    results: Sequence[EvaluationResult],
    prompt_before: str,
    prompt_after: str,
    optimizer_request: dict,
    optimizer_response: dict,
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    summary = _summary(phase, results)
    _write_json(run_dir / "summary.json", summary)
    _write_json(run_dir / "failure-clusters.json", summary["failure_categories"])
    _write_json(run_dir / "optimizer-request.json", _sanitize(optimizer_request))
    _write_json(run_dir / "optimizer-response.json", _sanitize(optimizer_response))
    (run_dir / "prompt-before.js").write_text(prompt_before, encoding="utf-8")
    (run_dir / "prompt-after.js").write_text(prompt_after, encoding="utf-8")
    (run_dir / "prompt.diff").write_text(
        "".join(
            difflib.unified_diff(
                prompt_before.splitlines(True),
                prompt_after.splitlines(True),
                fromfile="prompt-before.js",
                tofile="prompt-after.js",
            )
        ),
        encoding="utf-8",
    )
    with (run_dir / "failures.jsonl").open("w", encoding="utf-8") as handle:
        for result in results:
            if result.failure_category:
                handle.write(
                    json.dumps(
                        {
                            "row_number": result.sample.row_number,
                            "card_image": result.sample.card_image,
                            "expected": result.sample.expected_raw,
                            "actual": result.actual_numbers,
                            "failure_category": result.failure_category,
                            "image_status": result.image_status,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
    _write_results_xlsx(run_dir / "results.xlsx", results)
