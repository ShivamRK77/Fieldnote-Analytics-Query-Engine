"""Browser API and production static-file server for the analytics query engine."""
from __future__ import annotations

import copy
import logging
import re
import tempfile
from uuid import uuid4
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import RequestEntityTooLarge

from aqe.pipeline import Engine
from aqe.settings import Settings
from aqe.anomalies import generate_anomalies
from aqe.insights import generate_insights
from aqe.ingestion.upload import MAX_UPLOAD_BYTES, DatasetUploadError, stage_csv
from aqe.models import Unsupported

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "frontend" / "dist"
MODES = {"auto", "rules"}
log = logging.getLogger(__name__)
FILTER_FOLLOW_UP = re.compile(
    r"^only\s+show\s+(?P<dimension>[a-z0-9_ ]+?)\s+with\s+"
    r"(?P<metric>[a-z0-9_ ]+?)\s+"
    r"(?P<operator>greater\s+than|more\s+than|higher\s+than|lower\s+than|at\s+least|above|over|below|under)\s+"
    r"\$?(?P<value>\d[\d,]*(?:\.\d+)?)\s*[.!?]*$",
    re.IGNORECASE,
)
CONTEXTUAL_LANGUAGE = re.compile(
    r"\b(?:this|that|it|these|those|same)\b|"
    r"^\s*(?:only\s+show|show\s+only|filter\s+to|what\s+about|and\s+what\s+about)\b|"
    r"\bcompare\b.*\b(?:previous|prior|last)\s+year\b",
    re.IGNORECASE,
)


def _normalized_phrase(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9_]+", text.lower()))


def _phrase_in(text: str, phrase: str) -> bool:
    normalized_text = f" {_normalized_phrase(text)} "
    normalized_phrase = _normalized_phrase(phrase)
    return bool(normalized_phrase and f" {normalized_phrase} " in normalized_text)


def _mentions_semantic_term(text: str, aliases: dict[str, str], target: str) -> bool:
    return any(mapped == target and _phrase_in(text, alias) for alias, mapped in aliases.items())


def _resolve_filter_follow_up(active_query: str, question: str, engine: Engine) -> str | None:
    match = FILTER_FOLLOW_UP.fullmatch(question.strip())
    if not match:
        return None

    dimension_phrase = _normalized_phrase(match.group("dimension"))
    metric_phrase = _normalized_phrase(match.group("metric"))
    dimension = engine.sem.dimension_aliases.get(dimension_phrase)
    metric = engine.sem.metric_aliases.get(metric_phrase)
    if not dimension or not metric:
        return None
    if not _mentions_semantic_term(active_query, engine.sem.dimension_aliases, dimension):
        return None

    prior_metrics = {
        target for alias, target in engine.sem.metric_aliases.items()
        if _phrase_in(active_query, alias)
    }
    if prior_metrics != {metric}:
        return None

    operator = " ".join(match.group("operator").lower().split())
    value = match.group("value").replace(",", "")
    combined = f"{active_query.rstrip('. ')} {metric_phrase} {operator} {value}"
    try:
        plan = engine.rules.plan(combined)
    except Unsupported:
        return None
    if plan.unresolved or "HAVING" not in plan.sql.upper() or not _phrase_in(plan.sql, dimension):
        return None
    return combined


def _is_contextual_request(question: str) -> bool:
    return bool(CONTEXTUAL_LANGUAGE.search(question))


def _clarification_message(question: str, active_query: str | None, engine: Engine) -> str:
    if re.search(r"\b(?:previous|prior|last)\s+year\b", question, re.IGNORECASE):
        years = sorted(engine.sem.value_index.get("year", set()))
        if len(years) < 2:
            available = ", ".join(years) if years else "no years"
            return f"A previous-year comparison is unavailable: the dataset contains {available} only. Choose a comparison period present in the data."
    if not active_query:
        return "There is no active query to continue. Start with a complete analytics question."
    return f"I couldn't safely apply that follow-up to '{active_query}'. Please restate the complete question or specify the metric and dimension to change."


def _ambiguous_best_options(question: str, engine: Engine) -> list[dict[str, str]] | None:
    best_match = re.search(r"\bbest\b", question, re.IGNORECASE)
    if not best_match:
        return None
    if any(_phrase_in(question, alias) for alias in engine.sem.metric_aliases):
        return None

    normalized = _normalized_phrase(question)
    dimensions = []
    for alias, target in engine.sem.dimension_aliases.items():
        if target in ("month", "quarter", "year"):
            continue
        phrase = _normalized_phrase(alias)
        index = normalized.find(phrase)
        if phrase and index >= 0:
            dimensions.append((index, -len(phrase), phrase, target))
    dimensions = [item for item in dimensions if item[0] >= best_match.start()]
    if not dimensions:
        return None
    _, _, dimension_phrase, _ = min(dimensions)

    preferred = ["revenue", "profit", "orders"]
    metrics = [name for name in preferred if name in engine.sem.metrics]
    metrics.extend(name for name in engine.sem.metrics if name not in metrics)
    options = []
    for metric in metrics[:3]:
        label_name = metric.replace("_", " ").title()
        label = f"Most {label_name}" if metric == "orders" else f"Highest {label_name}"
        options.append({"label": label, "query": f"Top {dimension_phrase} by {metric}"})
    return options or None


def _metric_clarification_response(question: str, options: list[dict[str, str]],
                                   metadata: dict | None = None) -> dict:
    result_metadata = dict(metadata or {})
    result_metadata.update(
        clarification_required=True,
        clarification_type="ambiguous_metric",
        clarification="What does 'best' mean?",
        clarification_options=options,
    )
    return {
        "query": question,
        "generated_logic": "",
        "result": [],
        "confidence_score": 0.0,
        "explanation": "What does 'best' mean?",
        "metadata": result_metadata,
    }


def _record_turn(context: dict, question: str) -> None:
    context["history"].append(question)
    del context["history"][:-20]


def _add_conversation_metadata(result: dict, conversation_id: str, context: dict, is_follow_up: bool,
                               clarification: str | None = None) -> dict:
    metadata = result.setdefault("metadata", {})
    metadata.update(
        conversation_id=conversation_id,
        active_query=context["active_query"],
        conversation_history=list(context["history"]),
        is_follow_up=is_follow_up,
        clarification_required=clarification is not None,
    )
    if clarification is not None:
        metadata["clarification"] = clarification
    return result


def _discard_uploaded_dataset(context: dict) -> None:
    context.pop("dataset_engines", None)
    context.pop("dataset_dir", None)
    context.pop("dataset_schema", None)
    owner = context.pop("dataset_owner", None)
    if owner is not None:
        owner.cleanup()


def _map_uploaded_columns(result: dict, context: dict) -> dict:
    column_map = context.get("dataset_schema", {}).get("column_map", {})
    if column_map:
        result["result"] = [
            {column_map.get(column, column): value for column, value in row.items()}
            for row in result.get("result", [])
        ]
    return result


def _attach_insights(result: dict) -> dict:
    try:
        result["insights"] = generate_insights(result.get("query", ""), result.get("result", []))
    except Exception:
        log.exception("Insight generation failed; returning the query result without insights")
        result["insights"] = []
    try:
        result["anomalies"] = generate_anomalies(result.get("result", []))
    except Exception:
        log.exception("Anomaly detection failed; returning the query result without anomalies")
        result["anomalies"] = []
    return result


def create_app(engine: Engine | None = None) -> Flask:
    app = Flask(__name__, static_folder=str(DIST / "assets"), static_url_path="/assets")
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES + 64 * 1024
    app.config["AQE_ENGINE"] = engine
    app.config["AQE_ENGINES"] = {"auto": engine} if engine else {}
    app.config["AQE_CONVERSATIONS"] = {}

    def get_engine(mode: str) -> Engine:
        if engine is not None:
            return engine
        engines = app.config["AQE_ENGINES"]
        if mode not in engines:
            engines[mode] = Engine(Settings(), mode=mode)
        return engines[mode]

    def get_context_engine(context: dict, mode: str) -> Engine:
        dataset_dir = context.get("dataset_dir")
        if not dataset_dir:
            return get_engine(mode)
        effective_mode = "rules"
        engines = context.setdefault("dataset_engines", {})
        if effective_mode not in engines:
            settings = copy.copy(engine.s) if engine is not None else Settings()
            settings.dataset_dir = Path(dataset_dir)
            settings.overrides_path = Path(dataset_dir) / "semantic_overrides.json"
            settings.feedback_path = Path(dataset_dir) / "feedback_log.csv"
            engines[effective_mode] = Engine(settings, mode=effective_mode)
        return engines[effective_mode]

    def new_context() -> tuple[str, dict]:
        conversation_id = uuid4().hex
        context = {"active_query": None, "history": []}
        app.config["AQE_CONVERSATIONS"][conversation_id] = context
        return conversation_id, context

    @app.post("/api/conversation/new")
    def new_conversation():
        conversation_id, context = new_context()
        return jsonify({"conversation_id": conversation_id, "active_query": context["active_query"]})

    @app.post("/api/conversation/reset")
    def reset_conversation():
        payload = request.get_json(silent=True) or {}
        previous_id = payload.get("conversation_id")
        if previous_id is not None and not isinstance(previous_id, str):
            return jsonify({"error": "conversation_id must be a string."}), 400
        if previous_id:
            previous_context = app.config["AQE_CONVERSATIONS"].pop(previous_id, None)
            if previous_context:
                _discard_uploaded_dataset(previous_context)
        conversation_id, context = new_context()
        return jsonify({"conversation_id": conversation_id, "active_query": context["active_query"]})

    @app.post("/api/dataset/upload")
    def upload_dataset():
        conversation_id = request.form.get("conversation_id", "")
        context = app.config["AQE_CONVERSATIONS"].get(conversation_id)
        if not conversation_id or context is None:
            return jsonify({"error": "Start a conversation before uploading a dataset."}), 400
        uploaded = request.files.get("file")
        if uploaded is None or not uploaded.filename:
            return jsonify({"error": "Choose a CSV file to upload."}), 400
        if Path(uploaded.filename).suffix.lower() != ".csv":
            return jsonify({"error": "Only CSV files are supported."}), 400

        content = uploaded.stream.read(MAX_UPLOAD_BYTES + 1)
        owner = tempfile.TemporaryDirectory(prefix="aqe-dataset-")
        candidate_context = {"dataset_dir": owner.name, "dataset_engines": {}, "dataset_schema": {}}
        try:
            schema = stage_csv(content, Path(owner.name))
            candidate_context["dataset_schema"] = schema
            candidate = get_context_engine(candidate_context, "rules")
            if not candidate.sem.metrics:
                raise DatasetUploadError("No usable metrics were detected in this CSV.")
        except DatasetUploadError as error:
            owner.cleanup()
            return jsonify({"error": str(error)}), 400
        except Exception:
            owner.cleanup()
            log.exception("Uploaded dataset could not initialize the query engine")
            return jsonify({"error": "The CSV passed basic checks but could not initialize the analytics engine."}), 422

        _discard_uploaded_dataset(context)
        context.update(candidate_context)
        context["dataset_owner"] = owner
        context["dataset_schema"] = schema
        context["active_query"] = None
        return jsonify({"source": "uploaded", "dataset": schema}), 201

    @app.post("/api/dataset/reset")
    def reset_dataset():
        payload = request.get_json(silent=True) or {}
        conversation_id = payload.get("conversation_id")
        if not isinstance(conversation_id, str) or conversation_id not in app.config["AQE_CONVERSATIONS"]:
            return jsonify({"error": "Conversation not found."}), 404
        context = app.config["AQE_CONVERSATIONS"][conversation_id]
        _discard_uploaded_dataset(context)
        context["active_query"] = None
        return jsonify({"source": "default", "active_query": None})

    @app.errorhandler(RequestEntityTooLarge)
    def upload_too_large(_error):
        return jsonify({"error": f"Uploads are limited to {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."}), 413

    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok", "service": "analytics-query-engine"})

    @app.post("/api/query")
    def query():
        payload = request.get_json(silent=True) or {}
        question = str(payload.get("question") or "").strip()
        mode = payload.get("mode", "auto")
        conversation_id = payload.get("conversation_id")
        if not question:
            return jsonify({"error": "Please enter a question."}), 400
        if not isinstance(mode, str) or mode not in MODES:
            return jsonify({"error": "Mode must be 'auto' or 'rules'."}), 400
        if conversation_id is not None and not isinstance(conversation_id, str):
            return jsonify({"error": "conversation_id must be a string."}), 400

        try:
            if not conversation_id:
                current_engine = get_engine(mode)
                options = _ambiguous_best_options(question, current_engine)
                if options:
                    result = _metric_clarification_response(
                        question, options,
                        {"planner": None, "llm_available": current_engine.llm is not None})
                    return jsonify(_attach_insights(result))
                result = current_engine.answer(question, verbose=True)
                return jsonify(_attach_insights(result))

            contexts = app.config["AQE_CONVERSATIONS"]
            context = contexts.setdefault(conversation_id, {"active_query": None, "history": []})
            active_query = context["active_query"]
            is_follow_up = False
            clarification = None
            result = None

            options = _ambiguous_best_options(question, get_context_engine(context, mode))
            if options:
                _record_turn(context, question)
                result = _metric_clarification_response(
                    question, options,
                    {"planner": None, "llm_available": get_context_engine(context, mode).llm is not None})
                result = _add_conversation_metadata(result, conversation_id, context, True,
                                                    result["metadata"]["clarification"])
                return jsonify(_attach_insights(result))

            if active_query:
                rules_engine = get_context_engine(context, "rules")
                combined = _resolve_filter_follow_up(active_query, question, rules_engine)
                if combined:
                    result = rules_engine.answer(combined, verbose=True)
                    is_follow_up = True
                    if not result["generated_logic"]:
                        clarification = _clarification_message(question, active_query, rules_engine)
                elif _is_contextual_request(question):
                    clarification = _clarification_message(question, active_query, rules_engine)

            elif _is_contextual_request(question):
                rules_engine = get_context_engine(context, "rules")
                clarification = _clarification_message(question, None, rules_engine)

            if clarification is not None:
                _record_turn(context, question)
                result = {
                    "query": question,
                    "generated_logic": "",
                    "result": [],
                    "confidence_score": 0.0,
                    "explanation": clarification,
                    "metadata": {"planner": None, "llm_available": get_context_engine(context, mode).llm is not None},
                }
                result = _add_conversation_metadata(result, conversation_id, context, True, clarification)
                return jsonify(_attach_insights(result))

            if result is None:
                result = get_context_engine(context, mode).answer(question, verbose=True)
            if result["generated_logic"]:
                context["active_query"] = result["query"]
            _record_turn(context, question)
            result = _map_uploaded_columns(result, context)
            result = _add_conversation_metadata(result, conversation_id, context, is_follow_up)
            return jsonify(_attach_insights(result))
        except Exception as error:
            app.logger.exception("Query failed")
            return jsonify({"error": str(error)}), 500

    @app.get("/", defaults={"path": ""})
    @app.get("/<path:path>")
    def frontend(path: str):
        index = DIST / "index.html"
        if not index.is_file():
            return jsonify({"error": "Frontend build not found. Start it with 'npm run dev' in frontend/."}), 503
        if path and (DIST / path).is_file():
            return send_from_directory(DIST, path)
        return send_from_directory(DIST, "index.html")

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)