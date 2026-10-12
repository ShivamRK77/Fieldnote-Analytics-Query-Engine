# Intelligent Analytics Query Engine

Natural-language question -> **executable SQL** -> validated, sandboxed execution -> result, with a
**confidence score** and an **explanation** (what was understood, how it was produced).

```
python main.py run                              # answers dataset/nl_queries.json -> outputs/
python main.py ask "Top 3 cities by profit"     # ad-hoc question
python main.py -v ask "revenue last month"      # + metadata (planner, repairs, warnings)
python main.py feedback --query "..." --rating -1 --corrected-sql "SELECT ..."
python -m pytest -q tests                       # 30 tests
export ANTHROPIC_API_KEY=...                    # enables the GenAI planner (see "Modes")
```

Output per query (exactly the required contract):
`{"query", "generated_logic", "result", "confidence_score", "explanation"}`; `result` is a list of row objects.

## Web UI

Install the Python and frontend dependencies once:

```powershell
python -m pip install -r requirements.txt
cd frontend
npm install
```

Start the API from the project root in one terminal:

```powershell
python webapp.py
```

Start the React dev server from `frontend/` in a second terminal:

```powershell
npm run dev
```

Open `http://127.0.0.1:5173`. The development server proxies `/api` requests to Flask on port 5000. For a single production-style server, run `npm run build` from `frontend/`, then run `python webapp.py` from the project root and open `http://127.0.0.1:5000`.

Query results can be exported from the result panel as CSV or JSON. The PDF action opens a
print-ready report with the query, export date/time, confidence, actual result rows, available
visualization, key insights, and generated SQL; choose “Save as PDF” in the browser print dialog.
An empty result exports as an empty CSV and is explicitly identified in the PDF report.

## Approach

SQL is the executable form (SQLite, so windows/CTEs give top-N-per-group, share-of-total, growth, target joins).
Two independent planners produce SQL from the same **semantic layer**; the pipeline validates, executes,
cross-checks and scores.

1. **Semantic layer** (`aqe/semantic`) is built at runtime from `data_dictionary.json` + the live schema +
   `config/semantic_overrides.json`: metric -> aggregate SQL (`avg_order_value = revenue/orders` is composed from
   the other metrics), synonyms, dimension aliases/plurals, every real categorical value (for entity linking), and a
   time grammar (`last month`, `this quarter`, `Q1 2024`, `Feb`, ...).
2. **GenAI planner** (`planning/llm_planner.py`): the model gets the schema, real distinct values, metric
   definitions, synonyms, the `as_of` date and similar _verified_ past queries, and must answer through a forced
   tool call returning `{answerable, interpretation, sql, assumptions, self_confidence}`. SQL errors are fed back for
   up to 2 **self-repairs**.
3. **Rule planner** (`planning/rule_planner.py` + `sql_compiler.py`): a deterministic grammar over the same semantic layer
   (intents: aggregate, rank / top-N-per-group, contribution %, target comparison, growth). It is (a) the offline fallback
   and (b) an **independent second opinion** for the LLM. Not keyed on any query text.
4. **Execution guard** (`execution`): read-only in-memory SQLite with a SQLite _authorizer_ (SELECT/READ on whitelisted
   tables only), single statement, op budget, row cap. A literal-grounding check flags filters on values that do not exist
   (`region = 'Narnia'`).
5. **Confidence** (`scoring/confidence.py`): planners agree -> noisy-OR `1-(1-p1)(1-p2)`; disagree -> `0.4*max(p)`;
   then multiplicative penalties (ungrounded value, repair, empty result, all-NULL column, truncation, bad past rating); capped at 0.98.
   A transparent heuristic, **not** a calibrated probability.
6. **Performance** (`pipeline.py`, `execution/database.py`): verbose/API responses include measured total engine time,
   planner time (interpretation and SQL generation are reported together because the planner produces them in one call),
   SQL validation, database execution, and result formatting. Timings use a monotonic high-resolution clock and disclose
   no machine or server details.
7. **Explanation** (`explain/`): interpretation, term mapping, how it ran, cross-check result, assumptions, un-understood words,
   warnings, and the factors that moved confidence.
8. **Analytics anomalies** (`aqe/anomalies.py`): a separate, optional IQR scan of numeric query-result columns. It requires at
   least 10 valid values, excludes helper/identifier fields, reports the expected IQR fence and deviation, and labels findings
   as potential anomalies. Detection failures are logged and do not affect query execution or returned rows.
9. **Feedback loop** (`feedback/store.py`, `feedback_log.csv`, see `dataset/feedback_log.example.csv`): similar good/corrected
   queries become few-shot examples; a near-identical query with a corrected SQL is reused; a bad rating on the same SQL
   lowers confidence.

## Architecture

```
main.py (CLI)
 aqe/pipeline.py  Engine.answer()
   ingestion/   loader.py (repairs quote-wrapped CSV/JSON, keeps "NA"), profiler.py (data-quality checks)
   semantic/    layer.py (metrics, synonyms, dims, values), time_resolver.py
   planning/    llm_planner.py | rule_planner.py -> parsed.py -> sql_compiler.py
   llm/         client.py (Anthropic forced tool-use; swappable Protocol)
   execution/   database.py (sandbox), validator.py (literal grounding)
   scoring/     confidence.py     explain/ explainer.py     feedback/ store.py
 config/semantic_overrides.json   aqe/settings.py   tests/   outputs/   dataset/
```

## Modes

`auto` (default): LLM primary + rules cross-check if `ANTHROPIC_API_KEY` is set, otherwise rules only (stated in every
explanation). `--mode llm` requires a key; `--mode rules` forces offline. Model: `AQE_LLM_MODEL` (default `claude-sonnet-5-5`).
If the API fails, the engine degrades to the rule planner and says so.

## Assumptions & data findings

- **The supplied CSV/JSON files are malformed** (every line wrapped in quotes + BOM): the loader detects and repairs this.
  The region code `NA` would be read as NaN by pandas defaults, so all reads use `keep_default_na=False`.
- `revenue = quantity*unit_price*(1-discount)` (shipping excluded). Top-N within groups uses `RANK()`, so ties can return more than N rows.
- "Today" is outside the dataset, so relative phrases anchor to the latest `order_date` (`--as-of` overrides) and say so.
- The data covers one year, so **YoY growth is NULL**; the engine returns that, flags it and lowers confidence rather than inventing a number.
- Actual revenue is only ~1-12% of every monthly target, so "missed target" correctly returns all regions.
- `dimensions` in the dictionary omit customer/product; they are derived from the schema.
- Unknown proper-noun entities ("Narnia") are refused rather than silently dropped.

## Tradeoffs

- Direct SQL generation is flexible for unseen/nested questions but riskier than a typed plan; mitigated by the authorizer,
  grounding checks, self-repair and the second planner (cost: an extra deterministic pass, no extra API call).
- The rule grammar is deliberately narrow; phrasing outside it falls to the LLM (or is refused offline) instead of being guessed.
- Agreement between planners shares the same semantic layer, so a wrong metric definition would fool both.
- Results are compared ignoring column names and allowing an extra helper column, a pragmatic rather than exact equivalence test.

## Verification status (be aware)

- 30 tests pass: the 8 provided queries and 7 unseen phrasings checked against **independent pandas** calculations, 4 refusal cases,
  output contract, 9 GenAI-orchestration tests and the feedback loop.
- The **live Anthropic call was not exercised** (no API key in the build environment). The real SDK request and its tool-call parsing are untested; the orchestration around them is tested with a scripted model: repair, disagreement, unanswerable, outage fallback, hostile SQL, feedback reuse.
  Run once with a key and check `-v ask ...` before relying on it.

## If given more time

Calibrate confidence against a labelled feedback set; learn synonyms from corrections; typed-plan validation of LLM SQL (sqlglot);
multi-turn context; larger-data backends (DuckDB/warehouse) and result caching; metric-level ratio queries (margin %); per-city/product targets.
