import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.disable(logging.CRITICAL)

from aqe.ingestion import loader          # noqa: E402
from aqe.pipeline import Engine           # noqa: E402
from aqe.settings import Settings         # noqa: E402

DATASET = Path(__file__).resolve().parent.parent / "dataset"


class ScriptedLLM:
    """Stands in for the real model: returns queued tool-call payloads and records prompts."""
    def __init__(self, *responses):
        self.responses, self.prompts = list(responses), []

    def plan(self, system, user):
        self.prompts.append(user)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return {"answerable": True, "interpretation": "mock", "assumptions": [], "self_confidence": 0.9, **r}


@pytest.fixture
def settings(tmp_path):
    s = Settings()
    s.feedback_path = tmp_path / "feedback_log.csv"
    return s


@pytest.fixture
def engine(settings):
    return Engine(settings, mode="rules")


@pytest.fixture
def make_engine(settings):
    return lambda llm: Engine(settings, llm=llm, mode="auto")


@pytest.fixture(scope="session")
def sales():
    df = loader.load_sales(DATASET / "sales_data.csv")
    df["revenue"] = df.quantity * df.unit_price * (1 - df.discount)
    df["month"] = df.order_date.str[:7]
    return df


@pytest.fixture(scope="session")
def targets():
    return loader.load_targets(DATASET / "targets.csv")
