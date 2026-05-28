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

    samples = load_dataset(path, task="code")

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
        load_dataset(path, task="code")


def test_load_dataset_rejects_empty_workbook_without_header(tmp_path):
    path = tmp_path / "empty.xlsx"
    wb = Workbook()
    wb.save(path)

    with pytest.raises(
        ValueError,
        match="missing required columns: card_image, origin, md5_card_number",
    ):
        load_dataset(path, task="code")


def test_load_dataset_rejects_empty_image(tmp_path):
    path = tmp_path / "bad.xlsx"
    _write_xlsx(path, [["", 0, "1234"]])

    with pytest.raises(ValueError, match="row 2 has empty card_image"):
        load_dataset(path, task="code")


def test_empty_golden_answer_is_loaded_but_not_scoreable(tmp_path):
    path = tmp_path / "cards.xlsx"
    _write_xlsx(path, [["a.png", 0, ""]])

    samples = load_dataset(path, task="code")

    assert samples[0].scoreable is False


def test_load_type_dataset_requires_golden_type(tmp_path):
    path = tmp_path / "type.xlsx"
    _write_xlsx(path, [["a.png", 0, "Physics"]], headers=("card_image", "origin", "wrong"))

    with pytest.raises(ValueError, match="missing required columns: golden_type"):
        load_dataset(path, task="type")


def test_load_type_dataset_accepts_repeated_type_for_image_count(tmp_path):
    path = tmp_path / "type.xlsx"
    _write_xlsx(
        path,
        [["a.png||b.png", 0, "E-codesE-codes"]],
        headers=("card_image", "origin", "golden_type"),
    )

    samples = load_dataset(path, task="type")

    assert samples[0].card_image == "a.png||b.png"
    assert samples[0].expected_raw == "E-codesE-codes"
    assert samples[0].scoreable is True


@pytest.mark.parametrize("golden_type", ["PhysicsE-codes", "Physics", "UnknownUnknown"])
def test_load_type_dataset_rejects_invalid_repeated_type(tmp_path, golden_type):
    path = tmp_path / "type.xlsx"
    _write_xlsx(
        path,
        [["a.png||b.png", 0, golden_type]],
        headers=("card_image", "origin", "golden_type"),
    )

    with pytest.raises(ValueError, match="row 2 has invalid golden_type"):
        load_dataset(path, task="type")


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
