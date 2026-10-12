import io

from webapp import create_app


def test_query_api_returns_engine_result(engine):
    client = create_app(engine).test_client()

    response = client.post("/api/query", json={"question": "Total sales in India for March"})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["query"] == "Total sales in India for March"
    assert payload["result"][0]["revenue"] == 108.0
    assert payload["generated_logic"].startswith("SELECT")
    assert payload["metadata"]["planner"] == "rules"
    assert payload["metadata"]["performance"]["total_ms"] > 0
    assert payload["metadata"]["performance"]["stages_ms"]["database_execution"] >= 0
    assert payload["insights"] == []

    insights_response = client.post("/api/query", json={"question": "Top 2 cities by profit"})
    insights = insights_response.get_json()["insights"]
    assert insights
    assert all(insight["source"] == "deterministic" for insight in insights)


def test_flask_serves_assets_from_vite_build_assets_directory(monkeypatch, tmp_path):
    import webapp

    assets = tmp_path / "assets"
    assets.mkdir()
    (tmp_path / "index.html").write_text("<html>app</html>", encoding="utf-8")
    (assets / "app.css").write_text("body { color: green; }", encoding="utf-8")
    monkeypatch.setattr(webapp, "DIST", tmp_path)

    client = create_app().test_client()
    response = client.get("/assets/app.css")

    assert response.status_code == 200
    assert response.get_data(as_text=True) == "body { color: green; }"


def test_query_api_rejects_empty_question(engine):
    response = create_app(engine).test_client().post("/api/query", json={"question": " "})

    assert response.status_code == 400
    assert response.get_json() == {"error": "Please enter a question."}


def test_ambiguous_best_query_returns_metric_choices(engine):
    response = create_app(engine).test_client().post("/api/query", json={
        "question": "Show me the best cities",
        "mode": "rules",
    })

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["generated_logic"] == ""
    assert payload["result"] == []
    assert payload["metadata"]["clarification_required"] is True
    assert payload["metadata"]["clarification_type"] == "ambiguous_metric"
    assert payload["metadata"]["clarification"] == "What does 'best' mean?"
    assert [option["label"] for option in payload["metadata"]["clarification_options"]] == [
        "Highest Revenue", "Highest Profit", "Most Orders",
    ]
    assert [option["query"] for option in payload["metadata"]["clarification_options"]] == [
        "Top cities by revenue", "Top cities by profit", "Top cities by orders",
    ]


def test_explicit_metric_ranking_is_not_interrupted(engine):
    client = create_app(engine).test_client()
    session = client.post("/api/conversation/new").get_json()
    response = client.post("/api/query", json={
        "question": "Top 3 cities by profit",
        "mode": "rules",
        "conversation_id": session["conversation_id"],
    })

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["generated_logic"].startswith("SELECT")
    assert payload["result"]
    assert payload["metadata"]["clarification_required"] is False


def test_selected_clarification_option_continues_in_same_conversation(engine):
    client = create_app(engine).test_client()
    session = client.post("/api/conversation/new").get_json()
    ambiguous = client.post("/api/query", json={
        "question": "Show me the best cities",
        "mode": "rules",
        "conversation_id": session["conversation_id"],
    }).get_json()
    selected_query = next(option["query"] for option in ambiguous["metadata"]["clarification_options"]
                          if option["label"] == "Highest Profit")

    response = client.post("/api/query", json={
        "question": selected_query,
        "mode": "rules",
        "conversation_id": session["conversation_id"],
    })

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["metadata"]["clarification_required"] is False
    assert payload["generated_logic"].startswith("SELECT")
    assert payload["result"][0]["profit"] >= payload["result"][-1]["profit"]


def test_initial_query_starts_conversation(engine):
    client = create_app(engine).test_client()
    session = client.post("/api/conversation/new").get_json()

    response = client.post("/api/query", json={
        "question": "Top 3 cities by profit in India",
        "mode": "rules",
        "conversation_id": session["conversation_id"],
    })

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["metadata"]["conversation_id"] == session["conversation_id"]
    assert payload["metadata"]["active_query"] == "Top 3 cities by profit in India"
    assert payload["metadata"]["is_follow_up"] is False
    explain = payload["metadata"]["explain"]
    assert explain["metrics"] == ["profit"]
    assert explain["dimensions"] == ["cities"]
    assert explain["filters"] == ["india"]
    assert explain["ranking"] == "Ranked cities by profit"
    assert explain["limit"] == "3"
    assert "SELECT" not in explain["why"]


def test_explain_metadata_includes_grounded_time_range(engine):
    payload = create_app(engine).test_client().post("/api/query", json={
        "question": "Total sales in India for March",
    }).get_json()

    explain = payload["metadata"]["explain"]
    assert explain["metrics"] == ["sales"]
    assert explain["filters"] == ["india"]
    assert explain["time_range"] == "month:2024-03"


def test_filter_follow_up_uses_active_query(engine):
    client = create_app(engine).test_client()
    session = client.post("/api/conversation/new").get_json()
    initial = client.post("/api/query", json={
        "question": "Top 3 cities by profit in India", "mode": "rules",
        "conversation_id": session["conversation_id"],
    }).get_json()

    response = client.post("/api/query", json={
        "question": "Only show cities with profit greater than 20.",
        "mode": "rules",
        "conversation_id": session["conversation_id"],
    })

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["metadata"]["is_follow_up"] is True
    assert [(row["city"], row["profit"]) for row in payload["result"]] == [("Mumbai", 42.0), ("Delhi", 25.0)]
    assert "HAVING" in payload["generated_logic"]
    explain = payload["metadata"]["explain"]
    assert explain["ranking"] == "Ranked cities by profit"
    assert explain["limit"] == "3"
    assert "profit > 20.0" in explain["filters"]


def test_new_conversation_resets_backend_context(engine):
    client = create_app(engine).test_client()
    session = client.post("/api/conversation/new").get_json()
    initial = client.post("/api/query", json={
        "question": "Top 3 cities by profit in India", "mode": "rules",
        "conversation_id": session["conversation_id"],
    }).get_json()

    reset = client.post("/api/conversation/reset", json={"conversation_id": initial["metadata"]["conversation_id"]})
    new_id = reset.get_json()["conversation_id"]
    follow_up = client.post("/api/query", json={
        "question": "Only show cities with profit greater than 20.",
        "mode": "rules",
        "conversation_id": new_id,
    }).get_json()

    assert reset.status_code == 200
    assert new_id != session["conversation_id"]
    assert follow_up["metadata"]["active_query"] is None
    assert follow_up["metadata"]["clarification_required"] is True


def test_ambiguous_follow_up_requests_clarification(engine):
    client = create_app(engine).test_client()
    session = client.post("/api/conversation/new").get_json()
    initial = client.post("/api/query", json={
        "question": "Top 3 cities by profit in India", "mode": "rules",
        "conversation_id": session["conversation_id"],
    }).get_json()

    response = client.post("/api/query", json={
        "question": "Compare this with the previous year.",
        "mode": "rules",
        "conversation_id": session["conversation_id"],
    })

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["metadata"]["clarification_required"] is True
    assert payload["metadata"]["active_query"] == "Top 3 cities by profit in India"
    assert payload["generated_logic"] == ""
    assert payload["result"] == []


def test_invalid_standalone_query_does_not_become_context(engine):
    client = create_app(engine).test_client()
    session = client.post("/api/conversation/new").get_json()
    response = client.post("/api/query", json={
        "question": "what's the weather", "mode": "rules",
        "conversation_id": session["conversation_id"],
    })

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["generated_logic"] == ""
    assert payload["result"] == []
    assert payload["confidence_score"] == 0
    assert payload["metadata"]["active_query"] is None


def test_insight_failure_does_not_hide_successful_query(monkeypatch, engine):
    import webapp

    def fail_insights(query, rows):
        raise RuntimeError("insight generation failed")

    monkeypatch.setattr(webapp, "generate_insights", fail_insights)
    response = create_app(engine).test_client().post("/api/query", json={
        "question": "Total sales in India for March",
    })

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["result"][0]["revenue"] == 108.0
    assert payload["generated_logic"].startswith("SELECT")
    assert payload["insights"] == []


def test_anomaly_detection_failure_does_not_hide_successful_query(monkeypatch, engine):
    import webapp

    def fail_anomalies(rows):
        raise RuntimeError("anomaly detection failed")

    monkeypatch.setattr(webapp, "generate_anomalies", fail_anomalies)
    response = create_app(engine).test_client().post("/api/query", json={
        "question": "Total sales in India for March",
    })

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["result"][0]["revenue"] == 108.0
    assert payload["generated_logic"].startswith("SELECT")
    assert payload["anomalies"] == []


def test_query_api_returns_separate_anomaly_findings(monkeypatch, engine):
    import webapp

    finding = {
        "label": "Potential anomaly",
        "column": "revenue",
        "value": 100.0,
        "row_index": 10,
        "expected_range": {"lower": 5.5, "upper": 23.5},
        "deviation": {"amount": 76.5, "direction": "above", "percent": 325.53},
        "method": "IQR",
        "sample_size": 10,
    }
    monkeypatch.setattr(webapp, "generate_anomalies", lambda rows: [finding])
    response = create_app(engine).test_client().post("/api/query", json={
        "question": "Total sales in India for March",
    })

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["result"][0]["revenue"] == 108.0
    assert payload["anomalies"] == [finding]


def test_valid_upload_is_used_for_queries_then_default_can_be_restored(engine):
    client = create_app(engine).test_client()
    session = client.post("/api/conversation/new").get_json()
    upload = client.post("/api/dataset/upload", data={
        "conversation_id": session["conversation_id"],
        "file": (io.BytesIO(b"Region,Revenue,Order Date\nEast,20,2024-01-01\nWest,30,2024-01-04\n"), "sales.csv"),
    }, content_type="multipart/form-data")

    assert upload.status_code == 201
    schema = upload.get_json()["dataset"]
    assert schema["rows"] == 2 and schema["numeric_fields"] == ["Revenue"]
    assert schema["potential_metrics"] == ["Revenue"]
    assert schema["potential_dimensions"] == ["Region", "Order Date"]

    query = client.post("/api/query", json={
        "question": "Revenue by region",
        "mode": "rules",
        "conversation_id": session["conversation_id"],
    }).get_json()
    assert {row["Region"]: row["Revenue"] for row in query["result"]} == {"East": 20.0, "West": 30.0}
    assert not any("regions without targets" in warning for warning in query["metadata"]["data_warnings"])

    contribution = client.post("/api/query", json={
        "question": "Revenue contribution by Region",
        "mode": "rules",
        "conversation_id": session["conversation_id"],
    }).get_json()
    assert {row["Region"]: row["contribution_pct"] for row in contribution["result"]} == {
        "East": 40.0,
        "West": 60.0,
    }

    reset = client.post("/api/dataset/reset", json={"conversation_id": session["conversation_id"]})
    assert reset.status_code == 200
    default_query = client.post("/api/query", json={
        "question": "Total sales in India for March",
        "mode": "rules",
        "conversation_id": session["conversation_id"],
    }).get_json()
    assert default_query["result"][0]["revenue"] == 108.0


def test_invalid_uploads_are_rejected_and_do_not_replace_active_dataset(engine):
    client = create_app(engine).test_client()
    session = client.post("/api/conversation/new").get_json()
    upload = client.post("/api/dataset/upload", data={
        "conversation_id": session["conversation_id"],
        "file": (io.BytesIO(b"Region,Revenue\nEast,20\nWest,30\n"), "sales.csv"),
    }, content_type="multipart/form-data")
    assert upload.status_code == 201

    invalid = client.post("/api/dataset/upload", data={
        "conversation_id": session["conversation_id"],
        "file": (io.BytesIO(b"city,profit\nMumbai,10\nDelhi,20,extra\n"), "broken.csv"),
    }, content_type="multipart/form-data")

    assert invalid.status_code == 400
    query = client.post("/api/query", json={
        "question": "Revenue by region",
        "mode": "rules",
        "conversation_id": session["conversation_id"],
    }).get_json()
    assert {row["Region"]: row["Revenue"] for row in query["result"]} == {"East": 20.0, "West": 30.0}


def test_upload_rejects_non_csv_and_missing_conversation(engine):
    client = create_app(engine).test_client()
    session = client.post("/api/conversation/new").get_json()
    response = client.post("/api/dataset/upload", data={
        "conversation_id": session["conversation_id"],
        "file": (io.BytesIO(b"city,profit\nMumbai,10\n"), "sales.txt"),
    }, content_type="multipart/form-data")

    assert response.status_code == 400
    assert "CSV" in response.get_json()["error"]


def test_date_less_upload_answers_dimensions_without_inventing_time(engine):
    client = create_app(engine).test_client()
    session = client.post("/api/conversation/new").get_json()
    upload = client.post("/api/dataset/upload", data={
        "conversation_id": session["conversation_id"],
        "file": (io.BytesIO(b"Region,Revenue\nEast,20\nWest,30\n"), "sales.csv"),
    }, content_type="multipart/form-data")
    assert upload.status_code == 201

    aggregate = client.post("/api/query", json={
        "question": "Revenue by region", "mode": "auto",
        "conversation_id": session["conversation_id"],
    }).get_json()
    assert {row["Region"]: row["Revenue"] for row in aggregate["result"]} == {"East": 20.0, "West": 30.0}
    assert aggregate["metadata"]["planner"] == "rules"

    time_query = client.post("/api/query", json={
        "question": "Revenue by month", "mode": "rules",
        "conversation_id": session["conversation_id"],
    }).get_json()
    assert time_query["result"] == []
    assert time_query["generated_logic"] == ""
    assert "no usable date values" in time_query["explanation"]