const HELPER_COLUMN = /^(?:rank|rnk)$/i;
const DERIVED_COMPARISON_COLUMN = /^(?:previous_|prior_|top_\d+_total_)|(?:growth_pct|yoy_growth_pct)$/i;
const TIME_COLUMN = /^(?:date|order_date|month|quarter|year|period)$/i;
const PART_COLUMN = /(?:contribution|share|proportion|percent_of_total|pct_of_total)/i;

const VISUALIZATION_ORDER = ["table", "bars", "line", "pie", "area", "scatter", "metric"];

function isFiniteNumber(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function isTimeValue(column, value) {
  if (typeof value !== "string") return false;
  if (/^(?:month|period)$/i.test(column)) {
    return /^\d{4}(?:-\d{2}|-Q[1-4])?$/.test(value);
  }
  if (/^quarter$/i.test(column)) return /^\d{4}-Q[1-4]$/.test(value);
  if (/^year$/i.test(column)) return /^\d{4}$/.test(value);
  return /^\d{4}-\d{2}-\d{2}$/.test(value);
}

function isTimeSeriesColumn(column, rows) {
  return TIME_COLUMN.test(column) && rows.length > 1 && rows.every((row) => isTimeValue(column, row[column]));
}

function usablePartMeasure(measure, category, rows) {
  if (!measure || !category || rows.length < 2 || !PART_COLUMN.test(measure)) return false;
  const values = rows.map((row) => row[measure]);
  if (!values.every((value) => isFiniteNumber(value) && value >= 0) || !values.some((value) => value > 0)) return false;
  const total = values.reduce((sum, value) => sum + value, 0);
  return Math.abs(total - 100) <= 1 || Math.abs(total - 1) <= 0.01;
}

export function recommendVisualization(rows) {
  if (!Array.isArray(rows) || rows.length === 0 || !rows[0] || typeof rows[0] !== "object") {
    return { recommended: "table", options: ["table"], category: null, time: null, measures: [], partMeasure: null };
  }

  const columns = Object.keys(rows[0]);
  const measures = columns.filter((column) =>
    !HELPER_COLUMN.test(column) &&
    !DERIVED_COMPARISON_COLUMN.test(column) &&
    rows.some((row) => isFiniteNumber(row[column]))
  );
  const timeColumn = columns.find((column) =>
    TIME_COLUMN.test(column) && rows.every((row) => isTimeValue(column, row[column]))
  ) || null;
  const time = timeColumn && rows.length > 1 ? timeColumn : null;
  const category = columns.find((column) =>
    !TIME_COLUMN.test(column) &&
    !measures.includes(column) &&
    rows.every((row) => row[column] !== null && row[column] !== undefined) &&
    rows.some((row) => typeof row[column] === "string")
  ) || null;
  const partMeasure = measures.find((measure) => PART_COLUMN.test(measure)) || null;
  const isKpi = rows.length === 1 && measures.length > 0 && !category && !timeColumn;
  const options = new Set(["table"]);

  if (isKpi) options.add("metric");
  if (category && measures.length > 0) options.add("bars");
  if (time && measures.length > 0) {
    options.add("line");
    options.add("area");
  }
  if (usablePartMeasure(partMeasure, category, rows)) options.add("pie");
  if (rows.length > 1 && measures.length > 1) options.add("scatter");

  let recommended = "table";
  if (usablePartMeasure(partMeasure, category, rows)) recommended = "pie";
  else if (isKpi) recommended = "metric";
  else if (time && measures.length > 0) recommended = "line";
  else if (rows.length > 1 && measures.length > 1) recommended = "scatter";
  else if (category && measures.length > 0) recommended = "bars";

  return {
    recommended,
    options: VISUALIZATION_ORDER.filter((option) => options.has(option)),
    category,
    time,
    measures,
    partMeasure,
  };
}