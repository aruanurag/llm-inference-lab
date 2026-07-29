from __future__ import annotations

import os
from pathlib import Path


APP_NAME = "OCI Inference Cloud"
APP_DATA_DIR = Path(os.environ.get("OCI_INFERENCE_CLOUD_HOME", "~/.llm-inference-cloud")).expanduser()
KEYS_DIR = APP_DATA_DIR / "keys"
PROMPTS_DIR = APP_DATA_DIR / "prompts"
BENCHMARKS_DIR = APP_DATA_DIR / "benchmarks"
LOGS_DIR = APP_DATA_DIR / "logs"
LLMD_DIR = APP_DATA_DIR / "llm-d"
STATE_DB = APP_DATA_DIR / "state.db"


def ensure_app_dirs() -> None:
    for path in (APP_DATA_DIR, KEYS_DIR, PROMPTS_DIR, BENCHMARKS_DIR, LOGS_DIR, LLMD_DIR):
        path.mkdir(parents=True, exist_ok=True)
    KEYS_DIR.chmod(0o700)
