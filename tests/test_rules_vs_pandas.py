"""Every answer is checked against an independent pandas computation (not against SQL)."""
import pytest


def rows(o):
    return o["result"]


def test_total_sales_india_march(engine, sales):
    exp = sales[(sales.country == "India") & (sales.month == "2024-03")].revenue.sum()
    assert rows(engine.answer("Total sales in India for March"))[0]["revenue"] == pytest.approx(exp)


def test_top2_cities_profit(engine, sales):
    exp = sales.groupby("city").profit.sum().sort_values(ascending=False).head(2)
    got = rows(engine.answer("Top 2 cities by profit"))
    assert [(r["city"], r["profit"]) for r in got] == list(zip(exp.index, exp.values))


def test_rank_threshold_filters_before_limit(engine):
    got = rows(engine.answer("Top 3 cities by profit in India with profit greater than 20"))
    assert [(r["city"], r["profit"]) for r in got] == [("Mumbai", 42.0), ("Delhi", 25.0)]


def test_aov_by_region(engine, sales):
    g = sales.groupby("region").agg(r=("revenue", "sum"), n=("order_id", "count"))
    exp = (g.r / g.n).to_dict()
    got = {r["region"]: r["avg_order_value"] for r in rows(engine.answer("Average order value by region"))}
    assert got == pytest.approx(exp, abs=0.01)


def test_region_missed_target_feb(engine, sales, targets):
    act = sales[sales.month == "2024-02"].groupby("region").revenue.sum()
    t = targets[targets.month == "2024-02"].set_index("region").target_revenue
    exp = sorted(r for r in t.index if act.get(r, 0) < t[r])
    assert sorted(r["region"] for r in rows(engine.answer("Which region missed its target in Feb?"))) == exp


def test_contribution_sums_to_100(engine, sales):
    got = rows(engine.answer("Sales contribution % by category"))
    exp = (sales.groupby("product_category").revenue.sum() / sales.revenue.sum() * 100).to_dict()
    assert {r["product_category"]: r["contribution_pct"] for r in got} == pytest.approx(exp, abs=0.01)
    assert sum(r["contribution_pct"] for r in got) == pytest.approx(100, abs=0.05)


def test_top_product_each_region(engine, sales):
    g = sales.groupby(["region", "product_name"]).revenue.sum().reset_index()
    exp = g.loc[g.groupby("region").revenue.idxmax()].set_index("region").product_name.to_dict()
    got = {r["region"]: r["product_name"] for r in rows(engine.answer("Top product in each region"))}
    assert got == exp


def test_yoy_with_single_year_is_flagged(engine):
    o = engine.answer("YoY growth in revenue")
    assert o["result"][0]["yoy_growth_pct"] is None
    assert "NULL for every row" in o["explanation"]
    assert o["confidence_score"] < 0.8


def test_top3_customers_per_region(engine, sales):
    g = sales.groupby(["region", "customer_id"]).revenue.sum().reset_index()
    g["rk"] = g.groupby("region").revenue.rank(method="min", ascending=False)
    exp = {(r.region, r.customer_id) for r in g[g.rk <= 3].itertuples()}
    got = {(r["region"], r["customer_id"]) for r in rows(engine.answer("Revenue of top 3 customers per region"))}
    assert got == exp


def test_rank_threshold_filters_within_each_group(engine, sales):
    g = sales.groupby(["region", "customer_id"]).revenue.sum().reset_index()
    eligible = g[g.revenue > 500].copy()
    eligible["rk"] = eligible.groupby("region").revenue.rank(method="min", ascending=False)
    exp = {(r.region, r.customer_id) for r in eligible[eligible.rk <= 3].itertuples()}

    got = rows(engine.answer("Revenue of top 3 customers per region with revenue greater than 500"))

    assert {(r["region"], r["customer_id"]) for r in got} == exp
    assert all(r["revenue"] > 500 for r in got)


# ---- unseen phrasings -------------------------------------------------------------------
def test_region_NA_is_not_nan(engine, sales):
    o = engine.answer("total profit in NA")
    assert o["result"][0]["profit"] == sales[sales.region == "NA"].profit.sum()


def test_negation_filter(engine, sales):
    got = rows(engine.answer("revenue excluding India by region"))
    assert {r["region"] for r in got} == set(sales[sales.country != "India"].region)


def test_bottom_n(engine, sales):
    exp = sales.groupby("product_category").revenue.sum().sort_values().head(2).index.tolist()
    assert [r["product_category"] for r in rows(engine.answer("Bottom 2 categories by revenue"))] == exp


def test_two_dimensions(engine, sales):
    assert len(rows(engine.answer("Revenue by region and category"))) == sales.groupby(["region", "product_category"]).ngroups


def test_threshold_having(engine, sales):
    exp = sales.groupby("customer_id").revenue.sum()
    got = {r["customer_id"] for r in rows(engine.answer("Which customers have revenue above 500"))}
    assert got == set(exp[exp > 500].index)


def test_mom_growth(engine, sales):
    m = sales.groupby("month").revenue.sum()
    got = [r["growth_pct"] for r in rows(engine.answer("month over month growth in revenue"))]
    assert got[0] is None and got[1] == pytest.approx((m.iloc[1] / m.iloc[0] - 1) * 100, abs=0.01)


def test_relative_time_anchored_to_data(engine, sales):
    o = engine.answer("revenue last month")          # data ends 2024-03 -> last month = Feb
    assert o["result"][0]["revenue"] == sales[sales.month == "2024-02"].revenue.sum()
    assert "anchored" in o["explanation"]


# ---- edge cases -------------------------------------------------------------------------
@pytest.mark.parametrize("q", ["", "   ", "what's the weather", "sales in Narnia"])
def test_refuses_instead_of_guessing(engine, q):
    o = engine.answer(q)
    assert o["result"] == [] and o["confidence_score"] == 0.0 and o["explanation"]


def test_unknown_metric_for_target(engine):
    assert engine.answer("profit vs target by region")["confidence_score"] == 0.0


def test_output_contract(engine):
    o = engine.answer("Total sales in India for March")
    assert set(o) == {"query", "generated_logic", "result", "confidence_score", "explanation"}
    assert 0 <= o["confidence_score"] <= 1 and o["generated_logic"].lstrip().upper().startswith(("SELECT", "WITH"))


def test_verbose_output_includes_measured_performance_without_changing_default_contract(engine):
    result = engine.answer("Total sales in India for March", verbose=True)
    performance = result["metadata"]["performance"]

    assert set(performance) == {"total_ms", "stages_ms"}
    assert performance["total_ms"] > 0
    assert set(performance["stages_ms"]) == {
        "interpretation_and_sql_generation",
        "sql_validation",
        "database_execution",
        "result_formatting",
    }
    assert all(value >= 0 for value in performance["stages_ms"].values())
    assert set(engine.answer("Total sales in India for March")) == {
        "query", "generated_logic", "result", "confidence_score", "explanation",
    }
