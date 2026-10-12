import json

import pytest

from aqe.ingestion.upload import MAX_UPLOAD_BYTES, DatasetUploadError, stage_csv


def test_stage_csv_detects_schema_and_writes_engine_inputs(tmp_path):
    content = (
        b"Region,Revenue,Order Date\n"
        b"East,20,2024-01-01\n"
        b"West,30,2024-01-04\n"
    )

    schema = stage_csv(content, tmp_path)

    assert schema["rows"] == 2
    assert schema["columns"] == 3
    assert schema["numeric_fields"] == ["Revenue"]
    assert schema["categorical_fields"] == ["Region"]
    assert schema["date_fields"] == ["Order Date"]
    dictionary = json.loads((tmp_path / "data_dictionary.json").read_text())
    assert dictionary["metrics"]
    assert all(not expression.upper().startswith("SUM(") for expression in dictionary["metrics"].values())
    assert dictionary["dimensions"]
    assert (tmp_path / "sales_data.csv").is_file()
    assert (tmp_path / "targets.csv").is_file()
    assert (tmp_path / "semantic_overrides.json").is_file()


def test_date_less_upload_keeps_date_helper_empty(tmp_path):
    schema = stage_csv(b"Region,Revenue\nEast,20\nWest,30\n", tmp_path)

    assert schema["date_fields"] == []
    staged = (tmp_path / "sales_data.csv").read_text(encoding="utf-8").splitlines()
    headers, first_row = staged[0].split(","), staged[1].split(",")
    assert first_row[headers.index("order_date")] == ""


@pytest.mark.parametrize("content", [
    b"",
    b",,\n1,2,3\n",
    b"city,profit\nMumbai,10\nDelhi,20,extra\n",
    b"city,city\nMumbai,10\n",
    b"city,profit\nMumbai,not-a-number\n",
])
def test_invalid_csv_is_rejected_before_staging(tmp_path, content):
    with pytest.raises(DatasetUploadError):
        stage_csv(content, tmp_path)

    assert not (tmp_path / "sales_data.csv").exists()


def test_csv_with_no_numeric_or_dimension_fields_is_rejected(tmp_path):
    with pytest.raises(DatasetUploadError):
        stage_csv(b"note\nhello\nworld\n", tmp_path)

    assert not (tmp_path / "sales_data.csv").exists()


def test_oversized_upload_is_rejected(tmp_path):
    with pytest.raises(DatasetUploadError, match="upload limit"):
        stage_csv(b"x" * (MAX_UPLOAD_BYTES + 1), tmp_path)

    assert not (tmp_path / "sales_data.csv").exists()


def test_partial_month_names_are_not_promoted_to_full_dates(tmp_path):
    schema = stage_csv(b"Month,Revenue\nJan,10\nFeb,12\n", tmp_path)

    assert schema["date_fields"] == []
    assert schema["categorical_fields"] == ["Month"]