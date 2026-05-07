import asyncio

from openpyxl import Workbook

from optimizer.dataset import load_dataset, split_samples
from optimizer.evaluation import evaluate_samples
from optimizer.reporting import write_run_artifacts


class FakeRunner:
    async def run_one(self, payload):
        return {"status": 200, "data": [{"type": "E-codes", "number": payload.image}], "imageStatus": ["ok"]}


def test_tiny_evaluation_writes_artifacts(tmp_path):
    dataset = tmp_path / "cards.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["card_image", "origin", "md5_card_number"])
    ws.append(["ABC123", 0, "ABC123"])
    ws.append(["OIS", 0, "015"])
    wb.save(dataset)

    samples = load_dataset(dataset)
    split = split_samples(samples, dev_size=1, seed=1)
    results = asyncio.run(evaluate_samples(split.full, FakeRunner(), concurrency=2))
    write_run_artifacts(tmp_path / "run", "full", results, "old", "new", {}, {})

    assert (tmp_path / "run" / "summary.json").exists()
    assert (tmp_path / "run" / "results.xlsx").exists()
    assert (tmp_path / "run" / "prompt.diff").exists()
