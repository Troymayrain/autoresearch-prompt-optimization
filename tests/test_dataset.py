import pytest
from openpyxl import Workbook

from optimizer.dataset import load_dataset, split_samples


def _write_xlsx(path, rows, headers=("card_image", "origin", "md5_card_number")):
    wb = Workbook()
    ws = wb.active
    ws.append(list(headers))
    for row in rows:
        ws.append(row)
    wb.save(path)


def test_load_dataset_preserves_newline_golden_and_origin_int(tmp_path):
    path = tmp_path / "cards.xlsx"
    _write_xlsx(path, [["amazon_aws/card_img_tbay/a.png", "10", "ABCD\nEFGH"]])

    samples = load_dataset(path)

    assert len(samples) == 1
    assert samples[0].row_number == 2
    assert samples[0].card_image == "amazon_aws/card_img_tbay/a.png"
    assert samples[0].origin == 10
    assert samples[0].expected_raw == "ABCD\nEFGH"
    assert samples[0].scoreable is True


def test_load_dataset_rejects_missing_required_column(tmp_path):
    path = tmp_path / "bad.xlsx"
    _write_xlsx(path, [["a.png", 0, "1234"]], headers=("card_image", "origin", "wrong"))

    with pytest.raises(ValueError, match="missing required columns: md5_card_number"):
        load_dataset(path)


def test_load_dataset_rejects_empty_image(tmp_path):
    path = tmp_path / "bad.xlsx"
    _write_xlsx(path, [["", 0, "1234"]])

    with pytest.raises(ValueError, match="row 2 has empty card_image"):
        load_dataset(path)


def test_empty_golden_answer_is_loaded_but_not_scoreable(tmp_path):
    path = tmp_path / "cards.xlsx"
    _write_xlsx(path, [["a.png", 0, ""]])

    samples = load_dataset(path)

    assert samples[0].scoreable is False


def test_split_samples_is_deterministic():
    samples = [
        type("Sample", (), {"row_number": i})()
        for i in range(2, 12)
    ]

    first = split_samples(samples, dev_size=4, seed=17)
    second = split_samples(samples, dev_size=4, seed=17)

    assert [s.row_number for s in first.dev] == [s.row_number for s in second.dev]
    assert len(first.dev) == 4
    assert len(first.full) == 10
