"""Shared helpers for the nli_filter.py / nli_models.py tests (run from the project root: python -m pytest tests)."""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MODELS = ROOT / "models"


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: loads a real NLI model (skipped with -m 'not slow' or without ./models)")


class FakePool:
    """Stands in for NLIPool: deterministic scores from simple word rules, no model needed."""

    def __init__(self, name="fake", rules=None):
        self.name = name
        self.devices = ["cpu"]
        self.mode = "single"
        self.calls = 0
        self.pairs = 0
        self.rules = rules or {}

    def score(self, premises, hypotheses):
        self.calls += 1
        self.pairs += len(premises)
        out = []
        for p, h in zip(premises, hypotheses):
            low, hl = p.lower(), h.lower()
            if "company or brand" in hl:
                out.append(0.95 if ("company" in low or "brewing" in low) else 0.05)
            elif "language option" in hl:
                out.append(0.9 if "settings" in low else 0.02)
            else:  # check-1 topic hypothesis
                if "history" in low or "kremlin" in low or "largest country" in low:
                    out.append(0.97)
                elif "roulette" in low or "recipe" in low:
                    out.append(0.1)
                elif "uncertain" in low:
                    out.append(0.7)  # inside the default uncertain band -> judge
                else:
                    out.append(0.85 if "russia" in low else 0.05)
        return out

    def info(self):
        return {"model": self.name, "mode": self.mode, "devices": self.devices, "dtype": "float32",
                "max_length": 512, "load_seconds": 0.0}

    def close(self):
        pass


@pytest.fixture
def fake_pool():
    return FakePool


def models_available(*names):
    return all((MODELS / n / "config.json").is_file() for n in names)
