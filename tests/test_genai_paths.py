"""GenAI orchestration, exercised with a scripted model (no network)."""
from conftest import ScriptedLLM
from aqe.llm.client import LLMUnavailable

GOOD_TOTAL = "SELECT SUM(quantity*unit_price*(1-discount)) AS revenue FROM sales WHERE country='India' AND month='2024-03'"


def test_llm_and_rules_agree_boosts_confidence(make_engine, engine):
    llm = ScriptedLLM({"sql": GOOD_TOTAL, "self_confidence": 0.8})
    o = make_engine(llm).answer("Total sales in India for March", verbose=True)
    assert o["result"][0]["revenue"] == 108.0
    assert o["metadata"]["planner"] == "llm"
    assert o["metadata"]["explain"]["why"] == "mock"
    assert "matching result" in o["explanation"]
    assert o["confidence_score"] > engine.answer("Total sales in India for March")["confidence_score"] - 0.01


def test_disagreement_is_penalised_and_disclosed(make_engine):
    wrong = "SELECT SUM(profit) AS revenue FROM sales WHERE country='India'"
    o = make_engine(ScriptedLLM({"sql": wrong})).answer("Total sales in India for March")
    assert o["confidence_score"] <= 0.4
    assert "DIFFERENT" in o["explanation"]


def test_self_repair_loop(make_engine):
    llm = ScriptedLLM({"sql": "SELECT SUM(revnue) FROM sales"}, {"sql": GOOD_TOTAL})
    o = make_engine(llm).answer("Total sales in India for March", verbose=True)
    assert o["metadata"]["repairs"] == 1 and o["result"][0]["revenue"] == 108.0
    assert "no such column: revnue" in llm.prompts[1]       # the error was fed back
    assert "repair" in o["explanation"]


def test_unsafe_sql_never_executes(make_engine, engine):
    llm = ScriptedLLM({"sql": "DROP TABLE sales"}, {"sql": "DELETE FROM sales"}, {"sql": "SELECT 1; DROP TABLE sales"})
    o = make_engine(llm).answer("Total sales in India for March")
    # falls back to the rules planner; data still intact
    assert o["result"][0]["revenue"] == 108.0
    assert "failed validation" in o["explanation"]


def test_model_declares_unanswerable(make_engine):
    llm = ScriptedLLM({"answerable": False, "unanswerable_reason": "no weather data", "sql": ""})
    o = make_engine(llm).answer("will it rain tomorrow")
    assert o["result"] == [] and o["confidence_score"] == 0 and "no weather data" in o["explanation"]


def test_api_outage_degrades_to_rules(make_engine):
    o = make_engine(ScriptedLLM(LLMUnavailable("boom"))).answer("Total sales in India for March")
    assert o["result"][0]["revenue"] == 108.0 and "fell back to rules" in o["explanation"]


def test_ungrounded_literal_lowers_confidence(make_engine):
    sql = "SELECT SUM(quantity*unit_price*(1-discount)) AS revenue FROM sales WHERE country='Narnia'"
    o = make_engine(ScriptedLLM({"sql": sql})).answer("revenue in Narnia")
    assert o["result"][0]["revenue"] is None and o["confidence_score"] < 0.4
    assert "not a known value of country" in o["explanation"]


def test_feedback_correction_is_reused_and_examples_injected(settings, make_engine, engine):
    e = make_engine(ScriptedLLM())
    fixed = "SELECT region, SUM(profit) AS p FROM sales GROUP BY region"
    e.feedback_on("profit per region", "SELECT 1", -1, corrected=fixed, comment="wrong metric")
    o = e.answer("profit per region")                      # near-identical -> reuse, LLM not called
    assert o["generated_logic"] == fixed and "feedback" in o["explanation"].lower()
    llm = ScriptedLLM({"sql": GOOD_TOTAL})
    e2 = make_engine(llm)
    e2.answer("show profit by region and segment please")              # similar, not identical -> few-shot
    assert fixed in llm.prompts[0]


def test_bad_rating_penalises_same_sql(settings, make_engine, engine):
    q = "Total sales in India for March"
    base = engine.answer(q)
    engine.feedback_on(q, base["generated_logic"], -1)
    assert engine.answer(q)["confidence_score"] < base["confidence_score"]
