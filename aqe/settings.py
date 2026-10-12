"""Central configuration. Everything overridable through environment variables."""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    dataset_dir: Path = field(default_factory=lambda: Path(os.getenv("AQE_DATASET_DIR", ROOT / "dataset")))
    overrides_path: Path = ROOT / "config" / "semantic_overrides.json"
    feedback_path: Path = field(default_factory=lambda: Path(os.getenv("AQE_FEEDBACK_LOG", ROOT / "dataset" / "feedback_log.csv")))
    # LLM
    llm_model: str = os.getenv("AQE_LLM_MODEL", "claude-sonnet-5-5")
    llm_max_tokens: int = 1500
    llm_max_repairs: int = 2            # self-repair attempts after a failed SQL
    # Execution guard rails
    max_rows: int = 1000
    # "Today" for relative phrases (last month, this quarter). None => latest order_date in data.
    as_of: str | None = os.getenv("AQE_AS_OF") or None
    # Distinct-value grounding: columns with <= this many distinct values are shown to the LLM
    max_distinct_values_in_prompt: int = 50
    # Feedback
    feedback_similarity_threshold: float = 0.55
    feedback_reuse_threshold: float = 0.9
