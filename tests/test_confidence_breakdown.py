def test_breakdown_preserves_overall_score_and_only_scores_measured_component(engine):
    query = "Total sales in India for March"
    original = engine.answer(query)
    explained = engine.answer(query, verbose=True)
    breakdown = explained["metadata"]["confidence_breakdown"]
    components = {component["name"]: component for component in breakdown["components"]}

    assert explained["confidence_score"] == original["confidence_score"]
    assert breakdown["overall"] == explained["confidence_score"]
    assert breakdown["overall_state"] == "high"
    assert components["Query Understanding"]["percentage"] == 92
    assert components["Schema Match"]["state"] == "high"
    assert components["SQL Validation"]["state"] == "high"
    assert components["Execution Quality"]["state"] == "high"
    assert components["Result Quality"]["state"] == "high"
    assert all("percentage" not in component for name, component in components.items()
               if name != "Query Understanding")


def test_medium_result_quality_has_no_low_confidence_prompt(engine):
    answer = engine.answer("YoY growth in revenue", verbose=True)
    metadata = answer["metadata"]
    components = {component["name"]: component for component in metadata["confidence_breakdown"]["components"]}

    assert metadata["confidence_breakdown"]["overall_state"] == "medium"
    assert components["Result Quality"]["state"] == "low"
    assert metadata["clarification_suggestions"] == []


def test_unanswerable_query_suggests_supported_metrics(engine):
    answer = engine.answer("will it rain tomorrow", verbose=True)

    assert answer["confidence_score"] == 0
    assert answer["metadata"]["clarification_suggestions"]
    assert any("revenue" in suggestion.lower() for suggestion in answer["metadata"]["clarification_suggestions"])


def test_explainable_breakdown_uses_only_measured_percentages(engine):
    answer = engine.answer("Total sales in India for March", verbose=True)
    components = {component["name"]: component
                  for component in answer["metadata"]["confidence_breakdown"]["components"]}

    assert components["Query Understanding"]["percentage"] == 92
    for name in ("Schema Match", "SQL Validation", "Execution Quality", "Result Quality"):
        assert components[name]["state"] in {"high", "medium", "low", "not_measured"}
        assert "percentage" not in components[name]


def test_low_confidence_has_clarification_suggestions_and_unchanged_score(engine):
    answer = engine.answer("revenue in Narnia", verbose=True)
    breakdown = answer["metadata"]["confidence_breakdown"]

    assert answer["confidence_score"] == 0.0
    assert breakdown["overall"] == answer["confidence_score"]
    assert breakdown["overall_state"] == "low"
    query_understanding = next(component for component in breakdown["components"]
                               if component["name"] == "Query Understanding")
    assert query_understanding["state"] == "not_measured"
    assert "percentage" not in query_understanding
    assert answer["metadata"]["clarification_suggestions"]
    assert any("dataset" in suggestion.lower() or "metric" in suggestion.lower()
               for suggestion in answer["metadata"]["clarification_suggestions"])