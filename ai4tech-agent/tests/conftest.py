import json
from pathlib import Path

import pytest

from ai4tech.config import load_config

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"


@pytest.fixture
def config():
    return load_config(CONFIG_DIR)


@pytest.fixture
def golden_episode():
    return json.loads((GOLDEN_DIR / "episode.json").read_text())


@pytest.fixture
def golden_labels():
    return json.loads((GOLDEN_DIR / "labels.json").read_text())["labels"]


@pytest.fixture
def store(tmp_path):
    from ai4tech.state import StateStore

    s = StateStore(tmp_path / "state.db")
    yield s
    s.close()
