import { useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowDown,
  ArrowUpRight,
  Check,
  ChevronDown,
  CircleHelp,
  Clock3,
  Code2,
  Database,
  Download,
  FileJson,
  Layers3,
  LoaderCircle,
  Percent,
  Play,
  Plus,
  Sparkles,
  Table2,
  TrendingUp,
  Trophy,
  Upload,
  RotateCcw,
  X,
} from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { recommendVisualization } from "./visualization.js";
import { buildCsv, buildJson, buildPdfHtml, downloadFile } from "./exports.js";

const examples = [
  "Top 2 cities by profit",
  "Revenue by region and category",
  "Average order value by region",
  "Sales contribution % by category",
];
const BAR_CHART_FOLLOW_UP = /^(?:show|display|make|switch to)\s+(?:this|it|that)\s+as\s+(?:a\s+)?bar\s+chart[.!?]*$/i;
const CHART_COLORS = ["#236a52", "#d46a4e", "#c89d59", "#568da3", "#85a96e", "#87677c"];
const VISUALIZATION_LABELS = {
  table: "Table",
  bars: "Bars",
  line: "Line",
  pie: "Pie/Donut",
  area: "Area",
  scatter: "Scatter",
  metric: "Metric",
};
const PERFORMANCE_STAGE_LABELS = {
  interpretation_and_sql_generation: "Query interpretation & SQL generation",
  sql_validation: "SQL validation",
  database_execution: "Database execution",
  result_formatting: "Result formatting",
};

function formatValue(value) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") {
    return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value);
  }
  return String(value);
}

function formatMilliseconds(value) {
  return value < 10 ? `${value.toFixed(1)} ms` : `${Math.round(value)} ms`;
}

function BarsVisualization({ rows, model }) {
  const measure = model.measures[0];
  const label = model.category;
  if (!rows?.length || !measure || !label) return <ResultTable rows={rows} />;
  const maximum = Math.max(...rows.map((row) => Math.abs(Number(row[measure]) || 0)), 1);

  return (
    <div className="bar-chart" role="img" aria-label={`${measure} by ${label}`}>
      {rows.slice(0, 7).map((row, index) => (
        <div className="bar-row" key={`${row[label]}-${index}`}>
          <span className="bar-label" title={String(row[label])}>{String(row[label])}</span>
          <span className="bar-track"><span style={{ width: `${Math.max(3, Math.abs(Number(row[measure]) || 0) / maximum * 100)}%` }} /></span>
          <span className="bar-value">{formatValue(row[measure])}</span>
        </div>
      ))}
    </div>
  );
}

function MetricVisualization({ rows, measures }) {
  const values = measures.map((measure) => ({ measure, value: rows[0]?.[measure] })).filter(({ value }) => value !== null && value !== undefined);
  if (!values.length) return <ResultTable rows={rows} />;
  return <div className="metric-grid">{values.map(({ measure, value }) => (
    <div className="metric-tile" key={measure}><span>{measure.replaceAll("_", " ")}</span><strong>{formatValue(value)}</strong></div>
  ))}</div>;
}

function TimeVisualization({ rows, model, type }) {
  if (!model.time || !model.measures.length) return <ResultTable rows={rows} />;
  const Chart = type === "area" ? AreaChart : LineChart;
  const Series = type === "area" ? Area : Line;
  return (
    <div className="chart-frame" role="img" aria-label={`${VISUALIZATION_LABELS[type]} chart of ${model.measures.join(", ")} by ${model.time}`}>
      <ResponsiveContainer width="100%" height="100%">
        <Chart data={rows} margin={{ top: 12, right: 18, left: 2, bottom: 4 }}>
          <CartesianGrid stroke="#e7ebe5" strokeDasharray="3 4" vertical={false} />
          <XAxis dataKey={model.time} tick={{ fill: "#77827a", fontSize: 10 }} tickLine={false} axisLine={{ stroke: "#dce2da" }} />
          <YAxis tickFormatter={formatValue} tick={{ fill: "#879189", fontSize: 9 }} tickLine={false} axisLine={false} width={58} />
          <Tooltip formatter={(value) => formatValue(value)} />
          {model.measures.length > 1 && <Legend />}
          {model.measures.map((measure, index) => (
            <Series key={measure} type="monotone" dataKey={measure} name={measure.replaceAll("_", " ")} stroke={CHART_COLORS[index % CHART_COLORS.length]} fill={CHART_COLORS[index % CHART_COLORS.length]} fillOpacity={type === "area" ? 0.14 : 0} strokeWidth={2} dot={type === "line" ? { r: 3 } : false} activeDot={{ r: 5 }} />
          ))}
        </Chart>
      </ResponsiveContainer>
    </div>
  );
}

function PartToWholeVisualization({ rows, model }) {
  if (!model.category || !model.partMeasure) return <ResultTable rows={rows} />;
  return (
    <div className="chart-frame" role="img" aria-label={`Part-to-whole chart of ${model.partMeasure} by ${model.category}`}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Tooltip formatter={(value) => formatValue(value)} />
          <Legend />
          <Pie data={rows} dataKey={model.partMeasure} nameKey={model.category} innerRadius="48%" outerRadius="76%" paddingAngle={2}>
            {rows.map((row, index) => <Cell key={`${row[model.category]}-${index}`} fill={CHART_COLORS[index % CHART_COLORS.length]} />)}
          </Pie>
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}

function ScatterVisualization({ rows, model }) {
  if (model.measures.length < 2) return <ResultTable rows={rows} />;
  const [xMeasure, yMeasure] = model.measures;
  return (
    <div className="chart-frame" role="img" aria-label={`Scatter plot of ${yMeasure} against ${xMeasure}`}>
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 12, right: 18, left: 2, bottom: 4 }}>
          <CartesianGrid stroke="#e7ebe5" strokeDasharray="3 4" />
          <XAxis type="number" dataKey={xMeasure} name={xMeasure.replaceAll("_", " ")} tickFormatter={formatValue} tick={{ fill: "#77827a", fontSize: 9 }} />
          <YAxis type="number" dataKey={yMeasure} name={yMeasure.replaceAll("_", " ")} tickFormatter={formatValue} tick={{ fill: "#77827a", fontSize: 9 }} width={58} />
          <Tooltip cursor={{ strokeDasharray: "3 3" }} formatter={(value) => formatValue(value)} />
          <Scatter data={rows} fill={CHART_COLORS[0]} />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}

function VisualizationRenderer({ rows, model, type }) {
  if (!model.options.includes(type)) return <ResultTable rows={rows} />;
  if (type === "table") return <ResultTable rows={rows} />;
  if (type === "bars") return <BarsVisualization rows={rows} model={model} />;
  if (type === "metric") return <MetricVisualization rows={rows} measures={model.measures} />;
  if (type === "line" || type === "area") return <TimeVisualization rows={rows} model={model} type={type} />;
  if (type === "pie") return <PartToWholeVisualization rows={rows} model={model} />;
  if (type === "scatter") return <ScatterVisualization rows={rows} model={model} />;
  return <ResultTable rows={rows} />;
}

function KeyInsights({ insights, anomalies }) {
  if (!insights.length && !anomalies.length) return null;
  const icons = {
    leader: Trophy,
    share: Percent,
    difference: ArrowUpRight,
    trend: TrendingUp,
    ranking: TrendingUp,
  };

  return (
    <section className="insights-section" aria-labelledby="insights-heading">
      <div className="insights-heading">
        <div><Sparkles size={15} /><h3 id="insights-heading">Key insights</h3></div>
        <span>DETERMINISTIC · RETURNED DATA</span>
      </div>
      {insights.length > 0 && (
        <ul className="insights-list">
          {insights.map((insight, index) => {
            const Icon = icons[insight.icon] || Activity;
            const severity = ["positive", "info", "warning"].includes(insight.severity) ? insight.severity : "info";
            return (
              <li className={`insight-item severity-${severity}`} key={`${insight.icon}-${index}`}>
                <Icon size={15} aria-hidden="true" />
                <span>{insight.text}</span>
              </li>
            );
          })}
        </ul>
      )}
      {anomalies.length > 0 && (
        <div className="anomalies-block">
          <h4><AlertTriangle size={14} aria-hidden="true" />Potential anomalies</h4>
          <ul className="insights-list">
            {anomalies.map((anomaly, index) => {
              const { lower, upper } = anomaly.expected_range;
              const { amount, direction, percent } = anomaly.deviation;
              const boundary = direction === "above" ? "upper" : "lower";
              const deviation = `${formatValue(amount)} ${direction} the ${boundary} limit${
                percent === null ? "" : ` (${formatValue(percent)}%)`
              }`;
              return (
                <li className="insight-item severity-anomaly" key={`${anomaly.column}-${anomaly.row_index}-${index}`}>
                  <AlertTriangle size={15} aria-hidden="true" />
                  <span>
                    <strong>{anomaly.label}</strong> · Row {anomaly.row_index}: {anomaly.column.replaceAll("_", " ")} = {formatValue(anomaly.value)}
                    <br />Expected range: {formatValue(lower)}–{formatValue(upper)}
                    <br />Deviation: {deviation}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </section>
  );
}

function QueryExplanation({ answer, explain, onClose }) {
  const fields = [
    ["Metric", explain.metrics],
    ["Dimension", explain.dimensions],
    ["Filters", explain.filters],
    ["Ranking", explain.ranking],
    ["Limit", explain.limit],
    ["Time range", explain.time_range],
  ];
  const execution = [
    "Question interpreted",
    "Semantic mapping performed",
    "SQL generated",
    "SQL validated",
    `Query executed · ${answer.result.length} ${answer.result.length === 1 ? "row" : "rows"}`,
  ];

  return (
    <section className="query-explain-panel" aria-labelledby="query-explain-heading">
      <div className="query-explain-heading">
        <div><CircleHelp size={15} /><h3 id="query-explain-heading">Explain query</h3></div>
        <button className="query-explain-close" onClick={onClose} aria-label="Close query explanation"><X size={15} /></button>
      </div>
      <div className="query-explain-question"><span>QUESTION</span><p>{answer.query}</p></div>
      <div className="query-explain-grid">
        {fields.map(([label, value]) => (
          <div className="query-explain-field" key={label}>
            <span>{label}</span>
            <p>{Array.isArray(value) && value.length ? value.join(", ") : Array.isArray(value) ? "Not identified" : value || "Not specified"}</p>
          </div>
        ))}
      </div>
      <div className="query-explain-execution">
        <span>EXECUTION</span>
        <ol>{execution.map((step) => <li key={step}><span><Check size={10} /></span>{step}</li>)}</ol>
      </div>
      <div className="query-explain-why"><span>WHY THIS RESULT</span><p>{explain.why || "No additional interpretation metadata was recorded."}</p></div>
    </section>
  );
}

function ResultTable({ rows }) {
  if (!rows?.length) {
    return <div className="empty-result"><Table2 size={18} /><span>No rows returned for this question.</span></div>;
  }
  const columns = Object.keys(rows[0]);
  return (
    <div className="table-scroll">
      <table>
        <thead><tr>{columns.map((column) => <th key={column}>{column.replaceAll("_", " ")}</th>)}</tr></thead>
        <tbody>{rows.map((row, index) => (
          <tr key={index}>{columns.map((column) => <td key={column}>{formatValue(row[column])}</td>)}</tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function DataSourcePanel({ source, schema, busy, uploading, error, notice, onUpload, onReset }) {
  const inputRef = useRef(null);
  const fields = [
    ["Numeric fields", schema?.numeric_fields],
    ["Categorical fields", schema?.categorical_fields],
    ["Date fields", schema?.date_fields],
  ];

  return (
    <section className="data-source-panel" id="about" aria-labelledby="data-source-heading">
      <div className="data-source-heading">
        <div><span className="section-kicker">DATA SOURCE</span><h2 id="data-source-heading">Dataset</h2></div>
        <span className={`dataset-status ${source === "uploaded" ? "uploaded" : "default"}`}><span />{source === "uploaded" ? "UPLOADED CSV" : "BUNDLED DATASET"}</span>
      </div>
      <div className="data-source-controls">
        <div>
          <strong>{source === "uploaded" ? "Uploaded dataset is active" : "Sample sales dataset is active"}</strong>
          <p>{source === "uploaded" ? "This file is available only in the current conversation. Queries use the Rules planner." : "The bundled sales and target files remain available as the default."}</p>
        </div>
        <div className="data-source-actions">
          <input
            ref={inputRef}
            className="visually-hidden"
            type="file"
            accept=".csv,text/csv"
            aria-label="Upload CSV dataset"
            disabled={busy}
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) onUpload(file);
              event.target.value = "";
            }}
          />
          <button className="upload-button" onClick={() => inputRef.current?.click()} disabled={busy}>
            {uploading ? <LoaderCircle className="spin" size={15} /> : <Upload size={15} />}
            {uploading ? "Validating CSV" : "Upload CSV"}
          </button>
          {source === "uploaded" && <button className="restore-button" onClick={onReset} disabled={busy}><RotateCcw size={14} />Use default dataset</button>}
        </div>
      </div>
      {schema && (
        <div className="dataset-schema" aria-label="Detected dataset schema">
          <div className="dataset-counts"><span><strong>{schema.rows}</strong> rows</span><span><strong>{schema.columns}</strong> columns</span></div>
          <div className="schema-fields">
            {fields.map(([label, values]) => <div className="schema-field" key={label}><span>{label}</span><p>{values?.length ? values.join(", ") : "None detected"}</p></div>)}
            <div className="schema-field"><span>Potential metrics</span><p>{schema.potential_metrics?.length ? schema.potential_metrics.join(", ") : "None detected"}</p></div>
            <div className="schema-field"><span>Potential dimensions</span><p>{schema.potential_dimensions?.length ? schema.potential_dimensions.join(", ") : "None detected"}</p></div>
          </div>
        </div>
      )}
      {notice && <p className="data-source-notice" role="status">{notice}</p>}
      {error && <p className="data-source-error" role="alert">{error}</p>}
    </section>
  );
}

export default function App() {
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState("auto");
  const [answer, setAnswer] = useState(null);
  const [history, setHistory] = useState([]);
  const [conversationId, setConversationId] = useState(null);
  const [activeQuery, setActiveQuery] = useState(null);
  const [clarification, setClarification] = useState("");
  const [clarificationOptions, setClarificationOptions] = useState([]);
  const [busy, setBusy] = useState(false);
  const [datasetBusy, setDatasetBusy] = useState(false);
  const [datasetSource, setDatasetSource] = useState("default");
  const [datasetSchema, setDatasetSchema] = useState(null);
  const [datasetError, setDatasetError] = useState("");
  const [datasetNotice, setDatasetNotice] = useState("");
  const [error, setError] = useState("");
  const [view, setView] = useState("table");
  const [explainOpen, setExplainOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const rows = answer?.result || [];
  const insights = Array.isArray(answer?.insights) ? answer.insights : [];
  const anomalies = Array.isArray(answer?.anomalies) ? answer.anomalies : [];
  const visualization = recommendVisualization(rows);
  const activeView = visualization.options.includes(view) ? view : visualization.recommended;

  async function runQuery(value = question) {
    const text = value.trim();
    if (!text || busy || datasetBusy) return;
    setQuestion(text);
    if (answer && conversationId && BAR_CHART_FOLLOW_UP.test(text)) {
      if (visualization.options.includes("bars")) {
        setView("bars");
        setClarification("");
      } else {
        setClarification("Bars are not suitable for this result. The current table view is preserved.");
      }
      setClarificationOptions([]);
      return;
    }
    setBusy(true);
    setError("");
    setClarification("");
    setClarificationOptions([]);
    setCopied(false);
    try {
      let currentConversationId = conversationId;
      if (!currentConversationId) {
        const startResponse = await fetch("/api/conversation/new", { method: "POST" });
        const session = await startResponse.json();
        if (!startResponse.ok) throw new Error(session.error || "Could not start a conversation.");
        currentConversationId = session.conversation_id;
        setConversationId(currentConversationId);
      }
      const response = await fetch("/api/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: text, mode, conversation_id: currentConversationId }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "The query could not be completed.");
      const metadata = payload.metadata || {};
      setConversationId(metadata.conversation_id || currentConversationId);
      setActiveQuery(metadata.active_query || null);
      if (metadata.clarification_required) {
        setClarification(metadata.clarification || payload.explanation || "Please clarify the follow-up.");
        setClarificationOptions(metadata.clarification_options || []);
        return;
      }
      setAnswer(payload);
      setHistory((previous) => [text, ...previous.filter((item) => item !== text)].slice(0, 6));
      setView(recommendVisualization(payload.result).recommended);
      setExplainOpen(false);
      setClarificationOptions([]);
    } catch (requestError) {
      setError(requestError.message || "Could not connect to the query engine. Check that the API is running.");
    } finally {
      setBusy(false);
    }
  }

  async function startNewConversation() {
    if (busy || datasetBusy) return;
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/api/conversation/reset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conversation_id: conversationId }),
      });
      const session = await response.json();
      if (!response.ok) throw new Error(session.error || "Could not reset conversation context.");
      setConversationId(session.conversation_id);
      setActiveQuery(null);
      setDatasetSource("default");
      setDatasetSchema(null);
      setClarification("");
      setClarificationOptions([]);
      setAnswer(null);
      setQuestion("");
      setView("table");
      setExplainOpen(false);
      setCopied(false);
    } catch (requestError) {
      setConversationId(null);
      setError(requestError.message || "Could not reset the conversation.");
    } finally {
      setBusy(false);
    }
  }

  async function uploadDataset(file) {
    if (busy || datasetBusy) return;
    setDatasetBusy(true);
    setDatasetError("");
    setDatasetNotice("");
    try {
      let currentConversationId = conversationId;
      if (!currentConversationId) {
        const startResponse = await fetch("/api/conversation/new", { method: "POST" });
        const session = await startResponse.json();
        if (!startResponse.ok) throw new Error(session.error || "Could not start a conversation.");
        currentConversationId = session.conversation_id;
      }
      const form = new FormData();
      form.set("conversation_id", currentConversationId);
      form.set("file", file);
      const response = await fetch("/api/dataset/upload", { method: "POST", body: form });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "The CSV could not be activated.");
      setConversationId(currentConversationId);
      setDatasetSource("uploaded");
      setDatasetSchema(payload.dataset);
      setMode("rules");
      setActiveQuery(null);
      setAnswer(null);
      setQuestion("");
      setClarification("");
      setClarificationOptions([]);
      setView("table");
      setExplainOpen(false);
      setCopied(false);
      setDatasetNotice("CSV validated. The uploaded dataset is now active.");
    } catch (uploadError) {
      setDatasetError(uploadError.message || "Could not upload this CSV.");
    } finally {
      setDatasetBusy(false);
    }
  }

  async function restoreDefaultDataset() {
    if (!conversationId || busy || datasetBusy) return;
    setDatasetBusy(true);
    setDatasetError("");
    setDatasetNotice("");
    try {
      const response = await fetch("/api/dataset/reset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conversation_id: conversationId }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Could not restore the bundled dataset.");
      setDatasetSource("default");
      setDatasetSchema(null);
      setActiveQuery(null);
      setAnswer(null);
      setQuestion("");
      setClarification("");
      setClarificationOptions([]);
      setView("table");
      setExplainOpen(false);
      setCopied(false);
      setDatasetNotice("The bundled dataset is active again.");
    } catch (resetError) {
      setDatasetError(resetError.message || "Could not restore the bundled dataset.");
    } finally {
      setDatasetBusy(false);
    }
  }

  async function copySql() {
    if (!answer?.generated_logic) return;
    await navigator.clipboard.writeText(answer.generated_logic);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }

  function exportResults(format) {
    if (!answer) return;
    const baseName = "analytics-results";
    if (format === "csv") {
      downloadFile(buildCsv(rows), `${baseName}.csv`, "text/csv;charset=utf-8");
      return;
    }
    if (format === "json") {
      downloadFile(buildJson(answer), `${baseName}.json`, "application/json;charset=utf-8");
      return;
    }

    const reportWindow = window.open("", "_blank");
    if (!reportWindow) {
      setError("The PDF report could not open. Allow pop-ups for this site and try again.");
      return;
    }
    const visualizationElement = document.querySelector(
      ".result-primary .chart-frame, .result-primary .bar-chart, .result-primary .metric-grid",
    );
    const generatedAt = new Date().toLocaleString();
    reportWindow.document.open();
    reportWindow.document.write(buildPdfHtml(answer, generatedAt, visualizationElement?.outerHTML || ""));
    reportWindow.document.close();
    reportWindow.focus();
    reportWindow.print();
  }

  const metadata = answer?.metadata || {};
  const explain = metadata.explain || null;
  const confidence = answer?.confidence_score ?? 0;
  const confidencePercent = Math.round(confidence * 100);
  const confidenceBreakdown = metadata.confidence_breakdown;
  const confidenceState = confidenceBreakdown?.overall_state ||
    (confidencePercent >= 80 ? "high" : confidencePercent >= 50 ? "medium" : "low");
  const clarificationSuggestions = metadata.clarification_suggestions || [];
  const planner = metadata.planner || (mode === "rules" ? "rules" : "ready");
  const performance = metadata.performance;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#top" aria-label="Fieldnote home">
          <span className="brand-mark"><Activity size={18} strokeWidth={2.2} /></span>
          <span>fieldnote<span className="brand-period">.</span></span>
        </a>

        <div className="workspace-switcher">
          <span className="workspace-avatar">A</span>
          <span className="workspace-copy"><strong>Analytics team</strong><small>Local workspace</small></span>
          <ChevronDown size={15} />
        </div>

        <div className="nav-label">WORKSPACE</div>
        <nav className="side-nav" aria-label="Workspace">
          <a className="nav-item selected" href="#workspace"><Layers3 size={17} /><span>Query workspace</span><span className="nav-key">1</span></a>
          <a className="nav-item" href="#results"><Table2 size={17} /><span>Results</span></a>
          <a className="nav-item" href="#about"><Database size={17} /><span>Data source</span></a>
        </nav>

        <div className="history-heading"><span className="nav-label">RECENT QUERIES</span><button className="icon-button quiet" title="Clear recent queries" onClick={() => setHistory([])}><Plus size={15} /></button></div>
        <div className="history-list">
          {history.length ? history.map((item) => (
            <button className="history-item" key={item} onClick={() => runQuery(item)} title={item}><Clock3 size={14} /><span>{item}</span></button>
          )) : <p className="history-empty">Your recent questions will appear here.</p>}
        </div>

        <div className="sidebar-bottom">
          <div className="connection-status"><span className="online-dot" /><span>Engine connected</span><span className="connection-local">LOCAL</span></div>
          <a className="help-link" href="#about"><CircleHelp size={15} /> Engine details <ArrowUpRight size={13} /></a>
        </div>
      </aside>

      <main id="top" className="main-area">
        <header className="topbar">
          <div className="breadcrumbs"><span>Workspace</span><span className="crumb-slash">/</span><strong>Query workspace</strong></div>
          <div className="topbar-right"><span className="data-indicator"><span className="online-dot" />Sales dataset</span><span className="topbar-divider" /><label className="mode-select"><span>Mode</span><select value={mode} onChange={(event) => setMode(event.target.value)} aria-label="Select query mode"><option value="auto">Auto</option><option value="rules">Rules only</option></select><ChevronDown size={13} /></label></div>
        </header>

        <div className="content-wrap" id="workspace">
          {conversationId && activeQuery && <div className="conversation-strip"><div className="conversation-copy"><span className="conversation-label"><span className="conversation-dot" /> CONTINUING CONVERSATION</span><span className="conversation-active" title={activeQuery}>{activeQuery}</span></div><button className="new-conversation-button" onClick={startNewConversation} disabled={busy || datasetBusy}><Plus size={14} />New conversation</button></div>}
          {clarification && <div className="clarification-banner" role="status">
            <CircleHelp size={16} />
            <div className="clarification-content"><span>{clarification}</span>
              {clarificationOptions.length > 0 && <div className="clarification-options" role="group" aria-label="Clarification options">
                {clarificationOptions.map((option) => <button key={option.query} onClick={() => runQuery(option.query)} disabled={busy || datasetBusy}>{option.label}<ArrowUpRight size={12} /></button>)}
              </div>}
            </div>
            <button onClick={() => { setClarification(""); setClarificationOptions([]); }} aria-label="Dismiss clarification"><X size={14} /></button>
          </div>}
          <section className="workspace-intro">
            <div className="intro-copy"><div className="eyebrow"><span className="eyebrow-rule" /> BUSINESS INTELLIGENCE <span className="eyebrow-date">/ ORDERS · REGIONS · TARGETS</span></div><h1>Ask the <em>data.</em></h1><p>Sales dataset · 2024</p></div>
            <div className="intro-mark" aria-hidden="true"><div className="intro-mark-grid"><span /><span /><span /><span /><span /><span /><span /><span /><span /></div><span className="intro-mark-caption">SALES · 2024</span></div>
          </section>

          <section className="query-composer" aria-label="Ask a question">
            <div className="composer-topline"><span className="composer-label"><Sparkles size={15} /> NEW QUERY</span></div>
            <textarea
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); runQuery(); } }}
              placeholder="Ask something about your sales data..."
              rows={2}
              aria-label="Question about sales data"
            />
            <div className="composer-footer"><span className="composer-note">{datasetSource === "uploaded" ? "Uploaded dataset active" : "Sales dataset · 2024"}</span><button className="run-button" onClick={() => runQuery()} disabled={busy || datasetBusy || !question.trim()}>{busy || datasetBusy ? <LoaderCircle className="spin" size={16} /> : <Play size={15} fill="currentColor" />}<span>{datasetBusy ? "Dataset busy" : busy ? "Running query" : "Run query"}</span><span className="button-enter">↵</span></button></div>
          </section>

          <div className="suggestion-row"><span className="suggestion-label">TRY</span>{examples.map((example) => <button key={example} className="suggestion-chip" onClick={() => { setQuestion(example); runQuery(example); }} disabled={busy || datasetBusy}>{example}<ArrowUpRight size={12} /></button>)}</div>

          {error && <div className="error-banner" role="alert"><X size={17} /><span>{error}</span><button onClick={() => setError("")} aria-label="Dismiss error"><X size={15} /></button></div>}

          <section className="results-section" id="results">
            <div className="section-heading"><div><span className="section-kicker">WORKSPACE OUTPUT</span><h2>{answer ? "Query result" : "Ready when you are"}</h2></div><div className="result-meta">{answer ? <><span className="result-count">{rows.length} {rows.length === 1 ? "row" : "rows"}</span><span className="meta-divider" /><span>{metadata.planner || "engine"} planner</span>{Number.isFinite(performance?.total_ms) && <details className="performance-details"><summary>Query completed in {formatMilliseconds(performance.total_ms)}</summary><ul>{Object.entries(performance.stages_ms || {}).map(([stage, duration]) => <li key={stage}><span>{PERFORMANCE_STAGE_LABELS[stage] || stage.replaceAll("_", " ")}</span><strong>{formatMilliseconds(duration)}</strong></li>)}</ul></details>}</> : <span>Results will appear here</span>}</div></div>

            {busy ? (
              <div className="running-state"><div className="running-icon"><LoaderCircle className="spin" size={20} /></div><div><strong>Working through your question</strong><p>Planning, validating, and executing against the sales dataset.</p></div><span className="running-tag">IN PROGRESS</span></div>
            ) : answer ? (
              <div className="result-layout">
                <div className="result-primary">
                  <div className="result-toolbar">
                    <div className="visualization-controls">
                      <div className="segmented-control" role="tablist" aria-label="Result visualization">
                        {visualization.options.map((option) => (
                          <button key={option} className={activeView === option ? "active" : ""} role="tab" aria-selected={activeView === option} onClick={() => setView(option)} title={VISUALIZATION_LABELS[option]}>
                            {option === "table" ? <Table2 size={14} /> : <Activity size={14} />}
                            <span>{VISUALIZATION_LABELS[option]}</span>
                          </button>
                        ))}
                      </div>
                      <span className="recommendation-tag"><Sparkles size={12} />Recommended: <strong>{VISUALIZATION_LABELS[visualization.recommended]}</strong></span>
                    </div>
                    <span className="result-question">“{answer.query}”</span>
                    <div className="result-actions" role="group" aria-label="Export query results">
                      <button className="export-action" onClick={() => exportResults("csv")} title="Export results as CSV"><Download size={13} />CSV</button>
                      <button className="export-action" onClick={() => exportResults("json")} title="Export answer as JSON"><FileJson size={13} />JSON</button>
                      <button className="export-action" onClick={() => exportResults("pdf")} title="Print or save report as PDF"><Download size={13} />PDF</button>
                    </div>
                    {answer.generated_logic && <button className="explain-action" onClick={() => setExplainOpen((open) => !open)} aria-expanded={explainOpen}><CircleHelp size={14} />{explainOpen ? "Hide" : "Explain"}</button>}
                  </div>
                  <VisualizationRenderer rows={rows} model={visualization} type={activeView} />
                  {metadata.warnings?.length > 0 && <div className="warning-list">{metadata.warnings.map((warning) => <p key={warning}><CircleHelp size={14} />{warning}</p>)}</div>}
                </div>

                <aside className="inspector" aria-label="Query details">
                  <div className="inspector-block confidence-block">
                    <div className="inspector-title"><span>CONFIDENCE</span><span className={`confidence-state state-${confidenceState}`}><span className="confidence-dot" />{confidenceState.toUpperCase()}</span></div>
                    <div className="confidence-number">{confidencePercent}<small>%</small></div>
                    <div className="confidence-track"><span style={{ width: `${confidencePercent}%` }} /></div>
                    <p>Existing overall heuristic score.</p>
                    {confidenceBreakdown?.components && <div className="confidence-breakdown">
                      {confidenceBreakdown.components.map((component) => (
                        <div className="confidence-component" key={component.name}>
                          <div><strong>{component.name}</strong><span className={`component-state state-${component.state}`}>{component.state.replaceAll("_", " ")}</span></div>
                          {Number.isFinite(component.percentage) && <span className="component-percentage">{component.percentage}%</span>}
                          <small>{component.detail}</small>
                        </div>
                      ))}
                    </div>}
                    {confidenceState === "low" && clarificationSuggestions.length > 0 && <div className="clarification-suggestions"><strong>Try clarifying</strong><ul>{clarificationSuggestions.map((suggestion) => <li key={suggestion}>{suggestion}</li>)}</ul></div>}
                  </div>
                  <div className="inspector-block"><div className="inspector-title"><span>EXECUTION</span><span className="execution-mode">{planner.toUpperCase()}</span></div><ol className="execution-steps"><li className="complete"><span className="step-icon"><Check size={11} /></span><span><strong>Question interpreted</strong><small>{metadata.assumptions?.length ? `${metadata.assumptions.length} assumption${metadata.assumptions.length > 1 ? "s" : ""} recorded` : "Semantic layer mapped terms"}</small></span></li><li className="complete"><span className="step-icon"><Check size={11} /></span><span><strong>SQL validated</strong><small>{metadata.repairs ? `${metadata.repairs} repair${metadata.repairs === 1 ? "" : "s"} applied` : "Read-only execution guard"}</small></span></li><li className="complete"><span className="step-icon"><Check size={11} /></span><span><strong>Query executed</strong><small>{rows.length} result {rows.length === 1 ? "row" : "rows"}</small></span></li></ol></div>
                  <div className="inspector-block sql-block"><div className="inspector-title"><span><Code2 size={13} /> GENERATED SQL</span><button className="copy-button" onClick={copySql}>{copied ? <Check size={13} /> : <Layers3 size={13} />}{copied ? "Copied" : "Copy"}</button></div><pre>{answer.generated_logic || "-- no SQL generated"}</pre></div>
                  {metadata.assumptions?.length > 0 && <div className="inspector-block assumptions-block"><div className="inspector-title"><span>ASSUMPTIONS</span></div>{metadata.assumptions.map((assumption) => <p key={assumption}>{assumption}</p>)}</div>}
                </aside>
              </div>
            ) : (
              <div className="blank-state"><div className="blank-glyph"><span /><span /><span /><span /></div><div><strong>Awaiting first result</strong></div><ArrowDown className="blank-arrow" size={17} /></div>
            )}
            {answer?.generated_logic && explainOpen && explain && <QueryExplanation answer={answer} explain={explain} onClose={() => setExplainOpen(false)} />}
            {answer && <KeyInsights insights={insights} anomalies={anomalies} />}
          </section>

          {answer && <section className="explanation-row"><div className="explanation-label"><Sparkles size={14} /><span>ENGINE NOTES</span></div><p>{answer.explanation}</p></section>}

          <DataSourcePanel
            source={datasetSource}
            schema={datasetSchema}
            busy={busy || datasetBusy}
            uploading={datasetBusy}
            error={datasetError}
            notice={datasetNotice}
            onUpload={uploadDataset}
            onReset={restoreDefaultDataset}
          />

          <footer className="page-footer"><span><Database size={14} /> SQLite · read-only execution</span><span>Fieldnote <span className="footer-dot">/</span> Analytics Query Engine</span></footer>
        </div>
      </main>
    </div>
  );
}