from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from openpyxl import load_workbook

REQUIRED_COLUMNS = ("card_image", "origin", "md5_card_number")


@dataclass(frozen=True)
class Sample:
    row_number: int
    card_image: str
    origin: int
    expected_raw: str
    scoreable: bool


@dataclass(frozen=True)
class DatasetSplit:
    dev: list[Sample]
    full: list[Sample]


def _header_map(values: Sequence[object]) -> dict[str, int]:
    found: dict[str, int] = {}
    for idx, value in enumerate(values):
        key = str(value or "").strip()
        if key:
            found[key] = idx
    missing = [name for name in REQUIRED_COLUMNS if name not in found]
    if missing:
        raise ValueError(f"missing required columns: {', '.join(missing)}")
    return found


def _origin(value: object, row_number: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"row {row_number} has invalid origin: {value!r}") from None


def load_dataset(path: str | Path) -> list[Sample]:
    workbook = load_workbook(Path(path), read_only=True, data_only=True)
    try:
        worksheet = workbook.active
        rows = worksheet.iter_rows(values_only=True)
        headers = next(rows, ())

        columns = _header_map(headers)
        samples: list[Sample] = []
        for row_index, row in enumerate(rows, start=2):
            card_image = str(row[columns["card_image"]] or "").strip()
            if not card_image:
                raise ValueError(f"row {row_index} has empty card_image")
            expected_raw = str(row[columns["md5_card_number"]] or "").strip()
            samples.append(
                Sample(
                    row_number=row_index,
                    card_image=card_image,
                    origin=_origin(row[columns["origin"]], row_index),
                    expected_raw=expected_raw,
                    scoreable=bool(expected_raw),
                )
            )
        return samples
    finally:
        workbook.close()


def split_samples(samples: Sequence[Sample], dev_size: int, seed: int = 20260507) -> DatasetSplit:
    full = list(samples)
    shuffled = list(full)
    random.Random(seed).shuffle(shuffled)
    return DatasetSplit(dev=shuffled[: min(dev_size, len(shuffled))], full=full)
