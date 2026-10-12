import assert from "node:assert/strict";
import test from "node:test";
import { buildCsv, buildJson, buildPdfHtml } from "./exports.js";

test("CSV export quotes cells and preserves actual result values", () => {
  assert.equal(
    buildCsv([{ city: 'Mumbai, "West"', revenue: 42 }, { city: "Delhi", revenue: null }]),
    '"city","revenue"\r\n"Mumbai, ""West""","42"\r\n"Delhi",""',
  );
});

test("empty CSV exports no fabricated headers or rows", () => {
  assert.equal(buildCsv([]), "");
});

test("JSON export preserves the complete answer payload", () => {
  const answer = { query: "Sales", result: [{ revenue: 42 }], confidence_score: 0.8 };
  assert.deepEqual(JSON.parse(buildJson(answer)), answer);
});

test("PDF report includes answer details and gracefully handles empty results", () => {
  const html = buildPdfHtml({
    query: "<sales & profit>",
    confidence_score: 0.82,
    result: [],
    insights: [{ text: "A grounded insight" }],
    generated_logic: "SELECT revenue FROM sales",
  }, "2026-10-12 17:00", "<svg aria-label=\"Revenue chart\"></svg>");

  assert.match(html, /&lt;sales &amp; profit&gt;/);
  assert.match(html, /2026-10-12 17:00/);
  assert.match(html, /82%/);
  assert.match(html, /No rows returned for this query/);
  assert.match(html, /A grounded insight/);
  assert.match(html, /SELECT revenue FROM sales/);
  assert.match(html, /<svg aria-label="Revenue chart"><\/svg>/);
});

test("PDF report includes actual result rows and a no-insights message", () => {
  const html = buildPdfHtml({
    query: "Revenue by city",
    confidence_score: 0.5,
    result: [{ city: "Pune", revenue: 24 }],
    generated_logic: "",
  }, "now");

  assert.match(html, /<td>Pune<\/td><td>24<\/td>/);
  assert.match(html, /No key insights/);
  assert.match(html, /-- no SQL generated/);
  assert.doesNotMatch(html, /<section><h2>Visualization/);
});
