"""Shared job form and guide metadata; execution stays in registered handlers."""

import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def job_catalog():
    return json.loads(Path(__file__).with_suffix(".json").read_text(encoding="utf-8"))
