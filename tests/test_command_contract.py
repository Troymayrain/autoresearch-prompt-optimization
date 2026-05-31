import subprocess
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _poe_tasks():
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["tool"]["poe"]["tasks"]


def test_poe_tasks_select_expected_task_and_dataset_paths():
    tasks = _poe_tasks()

    assert tasks["code-smoke"]["cmd"] == (
        "python -m optimizer.autorun --task code --dataset 'datasets/IT-ST-RZ(TB)_1.xlsx'"
    )
    assert tasks["code-full"]["cmd"] == (
        "python -m optimizer.autorun --task code --dataset 'datasets/IT-ST-RZ(TB)_500.xlsx'"
    )
    assert tasks["type-smoke"]["cmd"] == (
        "python -m optimizer.autorun --task type --dataset 'datasets/type_ocr_1.xlsx'"
    )
    assert tasks["type-full"]["cmd"] == (
        "python -m optimizer.autorun --task type --dataset 'datasets/type_ocr_500.xlsx'"
    )


def test_autorun_help_requires_task_choice():
    result = subprocess.run(
        [sys.executable, "-m", "optimizer.autorun", "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "--task {code,type}" in result.stdout
    assert "--dataset DATASET" in result.stdout
    assert "--regression-dataset REGRESSION_DATASET" in result.stdout
    assert "--review-workbook REVIEW_WORKBOOK" in result.stdout
