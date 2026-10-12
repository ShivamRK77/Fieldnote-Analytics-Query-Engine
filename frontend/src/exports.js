function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatCell(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function buildCsv(rows) {
  if (!Array.isArray(rows) || rows.length === 0) return "";
  const columns = [...new Set(rows.flatMap((row) => Object.keys(row || {})))];
  const quote = (value) => `"${formatCell(value).replaceAll('"', '""')}"`;
  return [
    columns.map(quote).join(","),
    ...rows.map((row) => columns.map((column) => quote(row?.[column])).join(",")),
  ].join("\r\n");
}

export function buildJson(answer) {
  return JSON.stringify(answer, null, 2);
}

export function buildPdfHtml(answer, generatedAt, visualizationHtml = "") {
  const rows = Array.isArray(answer?.result) ? answer.result : [];
  const columns = [...new Set(rows.flatMap((row) => Object.keys(row || {})))];
  const table = rows.length
    ? `<table><thead><tr>${columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("")}</tr></thead><tbody>${
      rows.map((row) => `<tr>${columns.map((column) => `<td>${escapeHtml(formatCell(row?.[column]))}</td>`).join("")}</tr>`).join("")
    }</tbody></table>`
    : "<p>No rows returned for this query.</p>";
  const insights = (Array.isArray(answer?.insights) ? answer.insights : [])
    .map((insight) => `<li>${escapeHtml(insight.text)}</li>`);
  const anomalies = (Array.isArray(answer?.anomalies) ? answer.anomalies : [])
    .map((anomaly) => `<li><strong>${escapeHtml(anomaly.label || "Potential anomaly")}</strong>: ${escapeHtml(anomaly.column)} = ${escapeHtml(anomaly.value)}; expected range ${escapeHtml(anomaly.expected_range?.lower)}–${escapeHtml(anomaly.expected_range?.upper)}; deviation ${escapeHtml(anomaly.deviation?.amount)} ${escapeHtml(anomaly.deviation?.direction)}.</li>`);
  const findings = [...insights, ...anomalies];
  const visualization = visualizationHtml
    ? `<section><h2>Visualization</h2><div class="visualization">${visualizationHtml}</div></section>`
    : "";

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Analytics result</title>
<style>
  body { font: 12px Arial, sans-serif; color: #24312a; margin: 28px; }
  h1 { font-size: 22px; margin: 0 0 16px; }
  h2 { margin: 22px 0 8px; font-size: 15px; }
  p, pre { overflow-wrap: anywhere; }
  .meta { color: #526057; line-height: 1.7; }
  table { border-collapse: collapse; width: 100%; font-size: 10px; }
  th, td { border: 1px solid #cbd4cc; padding: 6px; text-align: left; overflow-wrap: anywhere; }
  th { background: #edf2ed; }
  pre { white-space: pre-wrap; background: #f3f5f2; padding: 10px; font: 10px monospace; }
  .visualization { max-width: 100%; }
  .visualization svg { max-width: 100%; height: auto; }
  .visualization .bar-chart { display: grid; gap: 8px; }
  .visualization .bar-row { display: grid; grid-template-columns: 1fr 2fr auto; gap: 8px; align-items: center; }
  .visualization .bar-track { height: 10px; background: #e7ebe5; }
  .visualization .bar-track span { display: block; height: 100%; background: #236a52; }
  .visualization .metric-grid { display: flex; gap: 12px; }
  .visualization .metric-tile { border: 1px solid #cbd4cc; padding: 12px; }
  .visualization .metric-tile span, .visualization .metric-tile strong { display: block; }
  @media print { body { margin: 14mm; } section, table, pre { break-inside: avoid; } }
</style>
</head>
<body>
  <h1>Analytics query result</h1>
  <div class="meta">
    <div><strong>Query:</strong> ${escapeHtml(answer?.query || "")}</div>
    <div><strong>Date/time:</strong> ${escapeHtml(generatedAt)}</div>
    <div><strong>Confidence:</strong> ${escapeHtml(`${Math.round((Number(answer?.confidence_score) || 0) * 100)}%`)}</div>
  </div>
  <section><h2>Results</h2>${table}</section>
  ${visualization}
  <section><h2>Key insights</h2>${findings.length ? `<ul>${findings.join("")}</ul>` : "<p>No key insights.</p>"}</section>
  <section><h2>Generated SQL</h2><pre>${escapeHtml(answer?.generated_logic || "-- no SQL generated")}</pre></section>
</body>
</html>`;
}

export function downloadFile(content, filename, type) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.style.display = "none";
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
