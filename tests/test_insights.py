from aqe.insights import generate_insights


def test_category_insights_use_only_returned_values():
    rows = [
        {"city": "Mumbai", "profit": 50.0},
        {"city": "Delhi", "profit": 30.0},
        {"city": "Pune", "profit": 20.0},
    ]

    insights = generate_insights("Top 3 cities by profit", rows)
    texts = [insight["text"] for insight in insights]

    assert any("Mumbai" in text and "highest" in text.lower() for text in texts)
    assert any("50.0%" in text and "displayed profit" in text for text in texts)
    assert any("40.0% less" in text and "Delhi" in text for text in texts)
    assert all(insight["source"] == "deterministic" for insight in insights)
    assert all(insight["severity"] in {"positive", "info", "warning"} for insight in insights)


def test_time_series_insight_reports_returned_change():
    rows = [
        {"month": "2024-01", "revenue": 100.0},
        {"month": "2024-02", "revenue": 125.0},
    ]

    insights = generate_insights("Revenue by month", rows)

    assert any("increased by 25.0%" in insight["text"] for insight in insights)
    assert any("2024-01" in insight["text"] and "2024-02" in insight["text"] for insight in insights)


def test_ranking_change_requires_matching_entities_across_periods():
    rows = [
        {"month": "2024-01", "city": "Mumbai", "profit": 50.0, "rank": 1},
        {"month": "2024-01", "city": "Delhi", "profit": 35.0, "rank": 2},
        {"month": "2024-02", "city": "Delhi", "profit": 45.0, "rank": 1},
        {"month": "2024-02", "city": "Mumbai", "profit": 40.0, "rank": 2},
    ]

    insights = generate_insights("Rank cities by profit by month", rows)

    assert any("Delhi" in insight["text"] and "moved up" in insight["text"] for insight in insights)


def test_insufficient_or_non_numeric_rows_produce_no_insights():
    assert generate_insights("revenue", []) == []
    assert generate_insights("unknown", [{"city": "Mumbai"}, {"city": "Delhi"}]) == []
    assert generate_insights("one row", [{"city": "Mumbai", "profit": 50.0}]) == []
