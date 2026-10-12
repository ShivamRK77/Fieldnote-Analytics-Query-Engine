#!/usr/bin/env python3
"""CLI for the Intelligent Analytics Query Engine.

  python main.py run                          # answer dataset/nl_queries.json -> outputs/
  python main.py ask "Top 3 cities by profit" # one ad-hoc question
  python main.py feedback --query "..." --rating -1 --corrected-sql "SELECT ..."
"""
from __future__ import annotations
import argparse
import json
import logging
import sys
from pathlib import Path

from aqe.ingestion.loader import load_json
from aqe.pipeline import Engine
from aqe.settings import Settings


def to_markdown(outputs: list[dict]) -> str:
    lines = ["# Sample outputs\n"]
    for i, o in enumerate(outputs, 1):
        lines += [f"## {i}. {o['query']}", f"**Confidence:** {o['confidence_score']}\n", "```sql", o["generated_logic"] or "-- none", "```"]
        rows = o["result"]
        if rows:
            cols = list(rows[0])
            lines += ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
            lines += ["| " + " | ".join("" if r[c] is None else str(r[c]) for c in cols) + " |" for r in rows]
        else:
            lines.append("_no rows_")
        lines += [f"\n**Explanation:** {o['explanation']}\n"]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["auto", "llm", "rules"], default="auto")
    ap.add_argument("--as-of", help="anchor date for relative phrases (default: latest order_date)")
    ap.add_argument("--dataset", help="dataset directory")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("--queries"); r.add_argument("--out", default="outputs")
    a = sub.add_parser("ask"); a.add_argument("question")
    f = sub.add_parser("feedback")
    f.add_argument("--query", required=True); f.add_argument("--rating", type=int, choices=[-1, 1], required=True)
    f.add_argument("--sql", default=""); f.add_argument("--corrected-sql", default=""); f.add_argument("--comment", default="")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO if args.verbose else logging.ERROR, format="%(levelname)s %(message)s")
    st = Settings()
    if args.as_of: st.as_of = args.as_of
    if args.dataset: st.dataset_dir = Path(args.dataset)
    engine = Engine(st, mode=args.mode)

    if args.cmd == "ask":
        print(json.dumps(engine.answer(args.question, args.verbose), indent=2, ensure_ascii=False))
    elif args.cmd == "feedback":
        engine.feedback_on(args.query, args.sql, args.rating, args.corrected_sql, args.comment)
        print(f"recorded in {st.feedback_path}")
    else:
        path = Path(args.queries) if args.queries else st.dataset_dir / "nl_queries.json"
        queries = [q["query"] for q in load_json(path)]
        outputs = [engine.answer(q, args.verbose) for q in queries]
        out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
        (out / "sample_outputs.json").write_text(json.dumps(outputs, indent=2, ensure_ascii=False))
        (out / "sample_outputs.md").write_text(to_markdown(outputs))
        for o in outputs:
            print(f"[{o['confidence_score']:.2f}] {o['query']}  ->  {len(o['result'])} row(s)")
        print(f"\nwritten to {out}/sample_outputs.json and .md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
