import assert from "node:assert/strict";
import test from "node:test";
import { recommendVisualization } from "../src/visualization.js";

test("time series recommends line and supports area", () => {
  const plan = recommendVisualization([
    { month: "2024-01", revenue: 120, orders: 3 },
    { month: "2024-02", revenue: 180, orders: 5 },
  ]);

  assert.equal(plan.recommended, "line");
  assert.deepEqual(plan.measures, ["revenue", "orders"]);
  assert.ok(plan.options.includes("area"));
});

test("category and numeric metric recommend bars", () => {
  const plan = recommendVisualization([
    { region: "APAC", revenue: 120 },
    { region: "EMEA", revenue: 250 },
  ]);

  assert.equal(plan.recommended, "bars");
  assert.ok(plan.options.includes("table"));
  assert.ok(plan.options.includes("bars"));
});

test("contribution results recommend pie only with usable parts", () => {
  const plan = recommendVisualization([
    { product_category: "Technology", contribution_pct: 88 },
    { product_category: "Furniture", contribution_pct: 12 },
  ]);

  assert.equal(plan.recommended, "pie");
  assert.ok(plan.options.includes("pie"));
});

test("partial contribution data does not offer a pie chart", () => {
  const plan = recommendVisualization([
    { product_category: "Technology", contribution_pct: 80 },
    { product_category: "Furniture", contribution_pct: 10 },
  ]);

  assert.notEqual(plan.recommended, "pie");
  assert.ok(!plan.options.includes("pie"));
});

test("two numeric metrics recommend scatter when no time axis exists", () => {
  const plan = recommendVisualization([
    { region: "APAC", revenue: 120, profit: 30 },
    { region: "EMEA", revenue: 250, profit: 45 },
  ]);

  assert.equal(plan.recommended, "scatter");
  assert.ok(plan.options.includes("scatter"));
});

test("a single numeric result recommends a metric card", () => {
  const plan = recommendVisualization([{ revenue: 6134.4 }]);

  assert.equal(plan.recommended, "metric");
  assert.ok(plan.options.includes("metric"));
});

test("a single categorized result is not mistaken for a KPI", () => {
  const plan = recommendVisualization([{ city: "Mumbai", profit: 42 }]);

  assert.equal(plan.recommended, "bars");
  assert.ok(!plan.options.includes("metric"));
});

test("a single time point does not become a KPI or trend chart", () => {
  const plan = recommendVisualization([{ year: "2024", revenue: 6134.4 }]);

  assert.equal(plan.recommended, "table");
  assert.deepEqual(plan.options, ["table"]);
});

test("unsuitable rows fall back to table without chart options", () => {
  const plan = recommendVisualization([
    { note: "unavailable", warning: "missing numeric result" },
    { note: "unknown", warning: "not computed" },
  ]);

  assert.equal(plan.recommended, "table");
  assert.deepEqual(plan.options, ["table"]);
});

test("empty results only support the table", () => {
  assert.deepEqual(recommendVisualization([]), {
    recommended: "table",
    options: ["table"],
    category: null,
    time: null,
    measures: [],
    partMeasure: null,
  });
});