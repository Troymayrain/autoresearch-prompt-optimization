from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    return default if value is None or value.strip() == "" else int(value)


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    return default if value is None or value.strip() == "" else float(value)


def _str_env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return default if value is None else value.strip()


@dataclass(frozen=True)
class OptimizerConfig:
    s3_read_region: str
    ocr_concurrency: int
    dev_sample_size: int
    target_business_accuracy: float
    plateau_window: int
    max_iterations: int
    no_card_failure_threshold: float
    prompt_path: Path
    runs_dir: Path
    optimizer_provider: str
    optimizer_model: str
    node_binary: str
    ocr_runner_path: Path

    @classmethod
    def from_env(cls, *, load_dotenv_file: bool = True) -> "OptimizerConfig":
        if load_dotenv_file:
            load_dotenv()
        return cls(
            s3_read_region=_str_env("S3_READ_REGION", "ap-east-1"),
            ocr_concurrency=_int_env("OCR_CONCURRENCY", 10),
            dev_sample_size=_int_env("DEV_SAMPLE_SIZE", 150),
            target_business_accuracy=_float_env("TARGET_BUSINESS_ACCURACY", 99.0),
            plateau_window=_int_env("PLATEAU_WINDOW", 3),
            max_iterations=_int_env("MAX_ITERATIONS", 15),
            no_card_failure_threshold=_float_env("NO_CARD_FAILURE_THRESHOLD", 5.0),
            prompt_path=Path(_str_env("PROMPT_PATH", "prompts/ocr.js")),
            runs_dir=Path(_str_env("RUNS_DIR", "runs")),
            optimizer_provider=_str_env("OPTIMIZER_PROVIDER", "openai").lower(),
            optimizer_model=_str_env("OPTIMIZER_MODEL", "gpt-5.5"),
            node_binary=_str_env("NODE_BINARY", "node"),
            ocr_runner_path=Path(_str_env("OCR_RUNNER_PATH", "ocr_runtime/run_ocr.js")),
        )
