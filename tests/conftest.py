import os
import sys
from pathlib import Path

os.environ.setdefault("DOCINV_DENSE", "0")      # deterministic, fast: lexical + char n-gram retrieval
os.environ.pop("ANTHROPIC_API_KEY", None)        # tests never call a real LLM
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from investigator import config
from investigator.engine import Engine


def _ensure_corpus():
    if not config.SAMPLES_DIR.exists() or len(list(config.SAMPLES_DIR.iterdir())) < 11:
        sys.path.insert(0, str(ROOT / "samples"))
        import generate_samples
        generate_samples.main()


@pytest.fixture()
def engine(tmp_path):
    return Engine(data_dir=tmp_path, dense=False)


@pytest.fixture(scope="session")
def demo_engine(tmp_path_factory):
    _ensure_corpus()
    eng = Engine(data_dir=tmp_path_factory.mktemp("demo"), dense=False)
    results = eng.load_demo()
    assert all(not r.get("error") for r in results)
    return eng


def add_text(engine, name, text):
    return engine.ingest(name, text.encode("utf-8"))["document"]
