from pathlib import Path

from optimizer.config import OptimizerConfig


def test_config_defaults(monkeypatch):
    for name in [
        "S3_READ_REGION",
        "OCR_CONCURRENCY",
        "DEV_SAMPLE_SIZE",
        "TARGET_BUSINESS_ACCURACY",
        "PLATEAU_WINDOW",
        "MAX_ITERATIONS",
        "NO_CARD_FAILURE_THRESHOLD",
    ]:
        monkeypatch.delenv(name, raising=False)

    cfg = OptimizerConfig.from_env()

    assert cfg.s3_read_region == "ap-east-1"
    assert cfg.ocr_concurrency == 10
    assert cfg.dev_sample_size == 150
    assert cfg.target_business_accuracy == 99.0
    assert cfg.plateau_window == 3
    assert cfg.max_iterations == 15
    assert cfg.no_card_failure_threshold == 5.0
    assert cfg.prompt_path == Path("prompts/ocr.js")


def test_config_reads_env_values(monkeypatch):
    monkeypatch.setenv("OCR_CONCURRENCY", "4")
    monkeypatch.setenv("DEV_SAMPLE_SIZE", "25")
    monkeypatch.setenv("TARGET_BUSINESS_ACCURACY", "98.5")
    monkeypatch.setenv("OPTIMIZER_PROVIDER", "openai")
    monkeypatch.setenv("OPTIMIZER_MODEL", "gpt-5.4")

    cfg = OptimizerConfig.from_env()

    assert cfg.ocr_concurrency == 4
    assert cfg.dev_sample_size == 25
    assert cfg.target_business_accuracy == 98.5
    assert cfg.optimizer_provider == "openai"
    assert cfg.optimizer_model == "gpt-5.4"
