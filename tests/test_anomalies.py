from aqe.anomalies import generate_anomalies


def test_iqr_anomaly_reports_value_range_and_deviation():
    rows = [{"revenue": value} for value in [10, 11, 12, 13, 14, 15, 16, 17, 18, 100]]

    anomalies = generate_anomalies(rows)

    assert len(anomalies) == 1
    anomaly = anomalies[0]
    assert anomaly["label"] == "Potential anomaly"
    assert anomaly["column"] == "revenue"
    assert anomaly["value"] == 100
    assert anomaly["row_index"] == 10
    assert anomaly["expected_range"] == {"lower": 5.5, "upper": 23.5}
    assert anomaly["deviation"] == {"amount": 76.5, "direction": "above", "percent": 325.531914893617}
    assert anomaly["method"] == "IQR"
    assert anomaly["sample_size"] == 10


def test_tiny_or_unusual_distributions_do_not_produce_anomalies():
    assert generate_anomalies([{"value": value} for value in range(9)]) == []
    assert generate_anomalies([{"value": value} for value in range(10)]) == []
    assert generate_anomalies([{"value": 5} for _ in range(12)]) == []


def test_helper_and_identifier_columns_are_not_scored():
    rows = [
        {"row_id": value, "rank": value, "revenue": value}
        for value in [1, 2, 3, 4, 5, 6, 7, 8, 9, 1000]
    ]

    anomalies = generate_anomalies(rows)

    assert [anomaly["column"] for anomaly in anomalies] == ["revenue"]


def test_invalid_rows_and_non_finite_values_are_ignored_safely():
    assert generate_anomalies([{"value": 1}, None] * 5) == []
    rows = [{"value": value} for value in [1, 2, 3, 4, 5, 6, 7, 8, 9, float("inf")]]
    assert generate_anomalies(rows) == []
