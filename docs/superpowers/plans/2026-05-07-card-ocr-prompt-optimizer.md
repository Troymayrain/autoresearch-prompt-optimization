# Card OCR Prompt Optimizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-contained gift-card OCR prompt optimization loop that evaluates Excel-labeled card images with the ordinary `code-ocr` OCR path, scores them with `card-type` business accuracy semantics, and automatically keeps only prompt changes that improve full-dataset accuracy.

**Architecture:** Python owns orchestration, dataset loading, scoring, reporting, optimizer LLM calls, and keep/discard control. A vendored Node runtime copied from `/Users/chushimima1234/projects/nodejs/code-ocr` owns the real ordinary OCR execution, while the optimizer may edit only top-level `prompts/ocr.js`. Discard restores the prompt from the saved pre-run file content, not by resetting the whole git worktree.

**Tech Stack:** Python 3, pytest, python-dotenv, openpyxl, XlsxWriter, Node.js CommonJS, AWS SDK for S3, existing `google-genai`/`anthropic`/`openai` provider clients.

---

## File Structure Map

Repository root: `/Users/chushimima1234/projects/python/autoresearch-prompt-optimization`

- Create `optimizer/__init__.py`: package marker.
- Create `optimizer/config.py`: `.env` and process environment config parser.
- Create `optimizer/dataset.py`: Excel loader, sample model, deterministic dev/full split.
- Create `optimizer/scoring.py`: business and strict normalization, matching, row scoring, aggregate metrics.
- Create `optimizer/node_runner.py`: Python async subprocess wrapper around the Node OCR runner.
- Create `optimizer/evaluation.py`: payload builder, concurrent evaluation, failure classification.
- Create `optimizer/reporting.py`: run directory artifacts, summary JSON, failures JSONL, result Excel, prompt diff.
- Create `optimizer/prompt_gate.py`: JavaScript syntax/export gate and prompt-only mutation guard.
- Create `optimizer/llm.py`: optimizer LLM request builder and JSON response parser.
- Create `optimizer/git_control.py`: prompt-only keep commit and content-based discard restore.
- Create `optimizer/autorun.py`: CLI and optimization loop.
- Create `ocr_runtime/`: vendored Node OCR runtime snapshot derived from `code-ocr`.
- Create `ocr_runtime/run_ocr.js`: stdin JSON to stdout JSON runner contract.
- Create `ocr_runtime/prompts/index.js`: bridge from runtime prompt imports to top-level `prompts/ocr.js`.
- Create `ocr_runtime/SOURCE.md`: source repository path, commit, copied file list, and local patches.
- Create `prompts/ocr.js`: baseline OCR prompt copied from `code-ocr/prompts/ocr.js`.
- Create `datasets/.gitkeep`: keep data directory without committing datasets.
- Create `runs/.gitkeep`: keep output directory while ignoring run artifacts.
- Create `tests/`: pytest suite for config, dataset, scoring, runner contract, reporting, prompt gate, and autorun.
- Modify `requirements.txt`: add test and Excel/report dependencies.
- Modify `.env.example`: document OCR evaluation and optimizer LLM environment variables.
- Modify `.gitignore`: ignore `.env`, `runs/*`, dataset spreadsheets, Node dependencies, and generated reports.
- Modify `README.md`: replace event-extraction quick start with card OCR optimizer workflow.

---

### Task 1: Project Skeleton, Dependencies, And Config

**Files:**
- Create: `optimizer/__init__.py`
- Create: `optimizer/config.py`
- Create: `tests/test_config.py`
- Modify: `requirements.txt`
- Modify: `.env.example`
- Modify: `.gitignore`

- [ ] **Step 1: Add dependency lines**

Modify `requirements.txt` so it contains the existing provider clients and these exact additional lines:

```text
pytest>=8.0.0
openpyxl>=3.1.0
XlsxWriter>=3.2.0
```

Expected: existing `google-genai`, `anthropic`, `openai`, and `python-dotenv` lines remain.

- [ ] **Step 2: Add config tests**

Create `tests/test_config.py`:

```python
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
```

- [ ] **Step 3: Run config tests and verify failure**

Run:

```bash
pytest tests/test_config.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'optimizer'`.

- [ ] **Step 4: Create config implementation**

Create `optimizer/__init__.py` as an empty file.

Create `optimizer/config.py`:

```python
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
    def from_env(cls) -> "OptimizerConfig":
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
            optimizer_provider=_str_env("OPTIMIZER_PROVIDER", "gemini").lower(),
            optimizer_model=_str_env("OPTIMIZER_MODEL", "gemini-2.5-flash"),
            node_binary=_str_env("NODE_BINARY", "node"),
            ocr_runner_path=Path(_str_env("OCR_RUNNER_PATH", "ocr_runtime/run_ocr.js")),
        )
```

- [ ] **Step 5: Update `.env.example`**

Ensure `.env.example` contains these keys:

```env
AWS_PROFILE=code-ocr-role
S3_READ_REGION=ap-east-1
S3_BUCKET_TB_GX=gx-card-pro
S3_BUCKET_TB_TBAY=tbay-card-prod
USE_LOCAL_IMAGES=false
ENABLE_S3_UPLOAD=false
DEC_SALT_TB=
DEC_SALT_CG=
DEC_SALT_TM=
AI_GATEWAY_URL=
AI_GATEWAY_KEY=
AI_GATEWAY_TIMEOUT_MS=80000
OCR_CONCURRENCY=10
DEV_SAMPLE_SIZE=150
TARGET_BUSINESS_ACCURACY=99.0
PLATEAU_WINDOW=3
MAX_ITERATIONS=15
NO_CARD_FAILURE_THRESHOLD=5.0
OPTIMIZER_PROVIDER=gemini
OPTIMIZER_MODEL=gemini-2.5-flash
GOOGLE_API_KEY=
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
```

- [ ] **Step 6: Update `.gitignore`**

Ensure `.gitignore` includes:

```gitignore
.env
runs/*
!runs/.gitkeep
datasets/*.xlsx
datasets/*.xls
datasets/*.csv
!datasets/.gitkeep
ocr_runtime/node_modules/
ocr_runtime/package-lock.json
```

- [ ] **Step 7: Verify and commit**

Run:

```bash
pytest tests/test_config.py -q
```

Expected: PASS.

Commit:

```bash
git add optimizer/__init__.py optimizer/config.py tests/test_config.py requirements.txt .env.example .gitignore
git commit -m "feat: add optimizer config foundation"
```

---

### Task 2: Excel Dataset Loader And Deterministic Split

**Files:**
- Create: `optimizer/dataset.py`
- Create: `tests/test_dataset.py`
- Create: `datasets/.gitkeep`

- [ ] **Step 1: Add loader tests**

Create `tests/test_dataset.py`:

```python
import pytest
from openpyxl import Workbook

from optimizer.dataset import load_dataset, split_samples


def _write_xlsx(path, rows, headers=("card_image", "origin", "md5_card_number")):
    wb = Workbook()
    ws = wb.active
    ws.append(list(headers))
    for row in rows:
        ws.append(row)
    wb.save(path)


def test_load_dataset_preserves_newline_golden_and_origin_int(tmp_path):
    path = tmp_path / "cards.xlsx"
    _write_xlsx(path, [["amazon_aws/card_img_tbay/a.png", "10", "ABCD\nEFGH"]])

    samples = load_dataset(path)

    assert len(samples) == 1
    assert samples[0].row_number == 2
    assert samples[0].card_image == "amazon_aws/card_img_tbay/a.png"
    assert samples[0].origin == 10
    assert samples[0].expected_raw == "ABCD\nEFGH"
    assert samples[0].scoreable is True


def test_load_dataset_rejects_missing_required_column(tmp_path):
    path = tmp_path / "bad.xlsx"
    _write_xlsx(path, [["a.png", 0, "1234"]], headers=("card_image", "origin", "wrong"))

    with pytest.raises(ValueError, match="missing required columns: md5_card_number"):
        load_dataset(path)


def test_load_dataset_rejects_empty_image(tmp_path):
    path = tmp_path / "bad.xlsx"
    _write_xlsx(path, [["", 0, "1234"]])

    with pytest.raises(ValueError, match="row 2 has empty card_image"):
        load_dataset(path)


def test_empty_golden_answer_is_loaded_but_not_scoreable(tmp_path):
    path = tmp_path / "cards.xlsx"
    _write_xlsx(path, [["a.png", 0, ""]])

    samples = load_dataset(path)

    assert samples[0].scoreable is False


def test_split_samples_is_deterministic():
    samples = [
        type("Sample", (), {"row_number": i})()
        for i in range(2, 12)
    ]

    first = split_samples(samples, dev_size=4, seed=17)
    second = split_samples(samples, dev_size=4, seed=17)

    assert [s.row_number for s in first.dev] == [s.row_number for s in second.dev]
    assert len(first.dev) == 4
    assert len(first.full) == 10
```

- [ ] **Step 2: Run loader tests and verify failure**

Run:

```bash
pytest tests/test_dataset.py -q
```

Expected: FAIL with `ModuleNotFoundError` or missing `load_dataset`.

- [ ] **Step 3: Implement loader**

Create `optimizer/dataset.py`:

```python
from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from openpyxl import load_workbook

REQUIRED_COLUMNS = ("card_image", "origin", "md5_card_number")


@dataclass(frozen=True)
class Sample:
    row_number: int
    card_image: str
    origin: int
    expected_raw: str
    scoreable: bool


@dataclass(frozen=True)
class DatasetSplit:
    dev: list[Sample]
    full: list[Sample]


def _header_map(values: Sequence[object]) -> dict[str, int]:
    found: dict[str, int] = {}
    for idx, value in enumerate(values):
        key = str(value or "").strip()
        if key:
            found[key] = idx
    missing = [name for name in REQUIRED_COLUMNS if name not in found]
    if missing:
        raise ValueError(f"missing required columns: {', '.join(missing)}")
    return found


def _origin(value: object, row_number: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"row {row_number} has invalid origin: {value!r}") from None


def load_dataset(path: str | Path) -> list[Sample]:
    workbook = load_workbook(Path(path), read_only=True, data_only=True)
    worksheet = workbook.active
    rows = worksheet.iter_rows(values_only=True)
    try:
        headers = next(rows)
    except StopIteration:
        return []

    columns = _header_map(headers)
    samples: list[Sample] = []
    for row_index, row in enumerate(rows, start=2):
        card_image = str(row[columns["card_image"]] or "").strip()
        if not card_image:
            raise ValueError(f"row {row_index} has empty card_image")
        expected_raw = str(row[columns["md5_card_number"]] or "").strip()
        samples.append(
            Sample(
                row_number=row_index,
                card_image=card_image,
                origin=_origin(row[columns["origin"]], row_index),
                expected_raw=expected_raw,
                scoreable=bool(expected_raw),
            )
        )
    return samples


def split_samples(samples: Sequence[Sample], dev_size: int, seed: int = 20260507) -> DatasetSplit:
    full = list(samples)
    shuffled = list(full)
    random.Random(seed).shuffle(shuffled)
    return DatasetSplit(dev=shuffled[: min(dev_size, len(shuffled))], full=full)
```

- [ ] **Step 4: Add dataset directory marker**

Run:

```bash
mkdir -p datasets
touch datasets/.gitkeep
```

Expected: `datasets/.gitkeep` exists and no spreadsheet is added.

- [ ] **Step 5: Verify and commit**

Run:

```bash
pytest tests/test_dataset.py -q
```

Expected: PASS.

Commit:

```bash
git add optimizer/dataset.py tests/test_dataset.py datasets/.gitkeep
git commit -m "feat: load card OCR Excel datasets"
```

---

### Task 3: Card-Type-Compatible Scoring Library

**Files:**
- Create: `optimizer/scoring.py`
- Create: `tests/test_scoring.py`

- [ ] **Step 1: Add scoring tests**

Create `tests/test_scoring.py`:

```python
from optimizer.scoring import (
    aggregate_scores,
    normalize_business,
    normalize_strict,
    score_row,
    split_codes,
)


def test_business_normalization_matches_card_type_rules():
    assert normalize_business(" ab-OI S\u3000-12 ") == "AB01512"


def test_strict_normalization_does_not_replace_ois():
    assert normalize_strict(" O-I-S ") == "OIS"


def test_split_codes_uses_newlines_and_filters_empty_values():
    assert split_codes("AAA\n\n BBB \r\n") == ["AAA", "BBB"]


def test_exact_then_includes_match_consumes_actual_once():
    result = score_row("ABC\nABC", ["ABC-999"])

    assert result.business_correct == 1
    assert result.business_total == 2
    assert result.unmatched_expected == ["ABC"]


def test_order_independent_multi_code_match():
    result = score_row("AAA\nBBB", ["xxxBBBxxx", "AAA"])

    assert result.business_correct == 2
    assert result.business_accuracy == 100.0


def test_empty_expected_is_skipped():
    result = score_row("", ["ANY"])

    assert result.business_total == 0
    assert result.business_accuracy == 0.0


def test_aggregate_scores_uses_business_metric_as_primary():
    summary = aggregate_scores([
        score_row("OIS", ["015"]),
        score_row("AAA", ["MISS"]),
    ])

    assert summary.business_total == 2
    assert summary.business_correct == 1
    assert summary.business_accuracy == 50.0
```

- [ ] **Step 2: Run scoring tests and verify failure**

Run:

```bash
pytest tests/test_scoring.py -q
```

Expected: FAIL with missing `optimizer.scoring`.

- [ ] **Step 3: Implement scoring**

Create `optimizer/scoring.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

BUSINESS_STRIP_RE = re.compile(r"[\n\r\t\v\f \u00A0\u3000-]+")


@dataclass(frozen=True)
class RowScore:
    expected_raw: str
    actual_raw: list[str]
    business_total: int
    business_correct: int
    strict_correct: int
    unmatched_expected: list[str]
    unmatched_actual: list[str]

    @property
    def business_accuracy(self) -> float:
        return 0.0 if self.business_total == 0 else round(self.business_correct / self.business_total * 100, 2)


@dataclass(frozen=True)
class ScoreSummary:
    business_total: int
    business_correct: int
    business_accuracy: float
    strict_correct: int
    strict_accuracy: float


def normalize_business(value: object) -> str:
    stripped = BUSINESS_STRIP_RE.sub("", str(value or ""))
    return stripped.upper().replace("O", "0").replace("I", "1").replace("S", "5")


def normalize_strict(value: object) -> str:
    return BUSINESS_STRIP_RE.sub("", str(value or "")).upper()


def split_codes(value: object) -> list[str]:
    return [part.strip() for part in str(value or "").splitlines() if part.strip()]


def _match(expected_raw: Sequence[str], actual_raw: Sequence[str], normalizer) -> tuple[int, list[str], list[str]]:
    expected_norm = [normalizer(item) for item in expected_raw if normalizer(item)]
    actual_norm = [normalizer(item) for item in actual_raw if normalizer(item)]
    used_actual = [False] * len(actual_norm)
    matched = [False] * len(expected_norm)

    for i, expected in enumerate(expected_norm):
        for j, actual in enumerate(actual_norm):
            if not used_actual[j] and actual == expected:
                used_actual[j] = True
                matched[i] = True
                break

    for i, expected in enumerate(expected_norm):
        if matched[i]:
            continue
        for j, actual in enumerate(actual_norm):
            if not used_actual[j] and expected in actual:
                used_actual[j] = True
                matched[i] = True
                break

    unmatched_expected = [expected_raw[i] for i, ok in enumerate(matched) if not ok]
    unmatched_actual = [actual_raw[i] for i, used in enumerate(used_actual) if not used]
    return sum(1 for ok in matched if ok), unmatched_expected, unmatched_actual


def score_row(expected_raw: object, actual_codes: Sequence[object]) -> RowScore:
    expected = split_codes(expected_raw)
    actual = [str(item or "").strip() for item in actual_codes if str(item or "").strip()]
    if not expected:
        return RowScore(str(expected_raw or ""), actual, 0, 0, 0, [], actual)
    business_correct, unmatched_expected, unmatched_actual = _match(expected, actual, normalize_business)
    strict_correct, _, _ = _match(expected, actual, normalize_strict)
    return RowScore(
        expected_raw=str(expected_raw or ""),
        actual_raw=actual,
        business_total=len([item for item in expected if normalize_business(item)]),
        business_correct=business_correct,
        strict_correct=strict_correct,
        unmatched_expected=unmatched_expected,
        unmatched_actual=unmatched_actual,
    )


def aggregate_scores(rows: Iterable[RowScore]) -> ScoreSummary:
    scored = list(rows)
    total = sum(row.business_total for row in scored)
    business_correct = sum(row.business_correct for row in scored)
    strict_correct = sum(row.strict_correct for row in scored)
    return ScoreSummary(
        business_total=total,
        business_correct=business_correct,
        business_accuracy=0.0 if total == 0 else round(business_correct / total * 100, 2),
        strict_correct=strict_correct,
        strict_accuracy=0.0 if total == 0 else round(strict_correct / total * 100, 2),
    )
```

- [ ] **Step 4: Verify and commit**

Run:

```bash
pytest tests/test_scoring.py -q
```

Expected: PASS.

Commit:

```bash
git add optimizer/scoring.py tests/test_scoring.py
git commit -m "feat: score OCR results with card-type rules"
```

---

### Task 4: Vendor Ordinary Code-OCR Runtime Snapshot

**Files:**
- Create: `ocr_runtime/ai-provider.js`
- Create: `ocr_runtime/handler-ocr.js`
- Create: `ocr_runtime/shared.js`
- Create: `ocr_runtime/utils.js`
- Create: `ocr_runtime/log-sanitizer.js`
- Create: `ocr_runtime/package.json`
- Create: `ocr_runtime/prompts/index.js`
- Create: `ocr_runtime/SOURCE.md`
- Create: `prompts/ocr.js`
- Create: `runs/.gitkeep`

- [ ] **Step 1: Copy runtime files**

Run:

```bash
mkdir -p ocr_runtime/prompts prompts runs
cp /Users/chushimima1234/projects/nodejs/code-ocr/ai-provider.js ocr_runtime/ai-provider.js
cp /Users/chushimima1234/projects/nodejs/code-ocr/handler-ocr.js ocr_runtime/handler-ocr.js
cp /Users/chushimima1234/projects/nodejs/code-ocr/shared.js ocr_runtime/shared.js
cp /Users/chushimima1234/projects/nodejs/code-ocr/utils.js ocr_runtime/utils.js
cp /Users/chushimima1234/projects/nodejs/code-ocr/log-sanitizer.js ocr_runtime/log-sanitizer.js
cp /Users/chushimima1234/projects/nodejs/code-ocr/prompts/ocr.js prompts/ocr.js
touch runs/.gitkeep
```

Expected: copied files exist under this repository; runtime no longer needs `/Users/chushimima1234/projects/nodejs/code-ocr` at execution time.

- [ ] **Step 2: Add prompt bridge**

Create `ocr_runtime/prompts/index.js`:

```javascript
module.exports = require('../../prompts/ocr');
```

Expected: `handler-ocr.js` keeps `require('./prompts')`, but it resolves to top-level `prompts/ocr.js`.

- [ ] **Step 3: Add runtime package file**

Create `ocr_runtime/package.json`:

```json
{
  "scripts": {
    "test": "node --test test/*.test.js",
    "check": "node --check run_ocr.js && node --check handler-ocr.js && node --check ../prompts/ocr.js"
  },
  "dependencies": {
    "@aws-sdk/client-s3": "^3.800.0",
    "@aws-sdk/s3-request-presigner": "^3.800.0",
    "axios": "^1.13.2",
    "crypto-js": "^4.2.0",
    "image-size": "^2.0.2"
  }
}
```

- [ ] **Step 4: Record source snapshot**

Run:

```bash
SOURCE_COMMIT="$(git -C /Users/chushimima1234/projects/nodejs/code-ocr rev-parse HEAD)"
cat > ocr_runtime/SOURCE.md <<EOF
# OCR Runtime Source

- Source repository: /Users/chushimima1234/projects/nodejs/code-ocr
- Source commit: ${SOURCE_COMMIT}
- Snapshot date: 2026-05-07

## Copied Files

- ai-provider.js
- handler-ocr.js
- shared.js
- utils.js
- log-sanitizer.js
- prompts/ocr.js copied to ../prompts/ocr.js

## Local Runtime Patch

- ocr_runtime/prompts/index.js re-exports ../../prompts/ocr so the optimizer has exactly one editable prompt file.
- ocr_runtime/package.json declares local runtime dependencies required by utils.js and ai-provider.js.
EOF
```

Expected: `ocr_runtime/SOURCE.md` contains the source commit.

- [ ] **Step 5: Install Node runtime dependencies**

Run:

```bash
cd ocr_runtime && npm install && cd ..
```

Expected: dependencies install without changing Python files. `ocr_runtime/node_modules/` and `ocr_runtime/package-lock.json` stay untracked because of `.gitignore`.

- [ ] **Step 6: Validate JavaScript syntax**

Run:

```bash
node --check prompts/ocr.js
node --check ocr_runtime/handler-ocr.js
node -e "const p=require('./prompts/ocr'); for (const k of ['PROMPT_PREFIX','PROMPT_SIMPLE','PROMPT_COMPLEX','PROMPT_COMPLET','PROMPT_DETECT']) if (!(k in p)) throw new Error(k)"
```

Expected: all commands exit 0.

- [ ] **Step 7: Commit snapshot**

Commit only source files, not Node dependencies:

```bash
git add ocr_runtime/ai-provider.js ocr_runtime/handler-ocr.js ocr_runtime/shared.js ocr_runtime/utils.js ocr_runtime/log-sanitizer.js ocr_runtime/package.json ocr_runtime/prompts/index.js ocr_runtime/SOURCE.md prompts/ocr.js runs/.gitkeep
git commit -m "feat: vendor ordinary code OCR runtime"
```

---

### Task 5: Node Runner Contract And Python Wrapper

**Files:**
- Create: `ocr_runtime/run_ocr.js`
- Create: `optimizer/node_runner.py`
- Create: `tests/test_node_runner.py`

- [ ] **Step 1: Add runner contract tests**

Create `tests/test_node_runner.py`:

```python
import json
import stat

import pytest

from optimizer.node_runner import OcrPayload, OcrRunner, OcrRunnerError


@pytest.mark.asyncio
async def test_node_runner_returns_json_payload(tmp_path):
    script = tmp_path / "fake_runner.js"
    script.write_text(
        """
        process.stdin.setEncoding('utf8');
        let body = '';
        process.stdin.on('data', chunk => body += chunk);
        process.stdin.on('end', () => {
          const payload = JSON.parse(body);
          console.error('log line');
          process.stdout.write(JSON.stringify({status: 200, data: [{type: 'E-codes', number: payload.image}], imageStatus: ['ok']}));
        });
        """,
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    runner = OcrRunner(node_binary="node", runner_path=script)

    result = await runner.run_one(OcrPayload(image="ABC123", origin=0))

    assert result["status"] == 200
    assert result["data"][0]["number"] == "ABC123"


@pytest.mark.asyncio
async def test_node_runner_rejects_non_json_stdout(tmp_path):
    script = tmp_path / "bad_runner.js"
    script.write_text("process.stdout.write('not-json')", encoding="utf-8")
    runner = OcrRunner(node_binary="node", runner_path=script)

    with pytest.raises(OcrRunnerError, match="invalid JSON stdout"):
        await runner.run_one(OcrPayload(image="x", origin=0))
```

- [ ] **Step 2: Run runner tests and verify failure**

Run:

```bash
pytest tests/test_node_runner.py -q
```

Expected: FAIL because `pytest-asyncio` is missing or `optimizer.node_runner` is missing.

- [ ] **Step 3: Add async test dependency**

Add this line to `requirements.txt`:

```text
pytest-asyncio>=0.23.0
```

Install dependencies before rerunning locally:

```bash
pip install -r requirements.txt
```

- [ ] **Step 4: Implement Python wrapper**

Create `optimizer/node_runner.py`:

```python
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class OcrRunnerError(RuntimeError):
    pass


@dataclass(frozen=True)
class OcrPayload:
    image: str
    origin: int
    channel: str = "TB"
    type: str = "complex"

    def to_json(self) -> str:
        return json.dumps(
            {"image": self.image, "origin": self.origin, "channel": self.channel, "type": self.type},
            ensure_ascii=False,
        )


class OcrRunner:
    def __init__(self, node_binary: str, runner_path: str | Path):
        self.node_binary = node_binary
        self.runner_path = Path(runner_path)

    async def run_one(self, payload: OcrPayload) -> dict[str, Any]:
        proc = await asyncio.create_subprocess_exec(
            self.node_binary,
            str(self.runner_path),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(payload.to_json().encode("utf-8"))
        if proc.returncode != 0:
            raise OcrRunnerError(stderr.decode("utf-8", errors="replace") or f"node exited {proc.returncode}")
        try:
            result = json.loads(stdout.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise OcrRunnerError(f"invalid JSON stdout: {stdout[:200]!r}") from exc
        if not isinstance(result, dict):
            raise OcrRunnerError("node runner returned non-object JSON")
        return result
```

- [ ] **Step 5: Add Node runner**

Create `ocr_runtime/run_ocr.js`:

```javascript
const { processOcrRequest } = require('./handler-ocr');

console.log = (...args) => console.error(...args);

function readStdin() {
  return new Promise((resolve, reject) => {
    let body = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', chunk => { body += chunk; });
    process.stdin.on('error', reject);
    process.stdin.on('end', () => resolve(body));
  });
}

async function main() {
  const body = await readStdin();
  const payload = JSON.parse(body || '{}');
  const response = await processOcrRequest(payload);
  process.stdout.write(JSON.stringify(response.body));
}

main().catch(error => {
  const message = error && error.message ? error.message : String(error);
  process.stdout.write(JSON.stringify({ status: 500, message: 'failed', error: message }));
  process.exitCode = 0;
});
```

- [ ] **Step 6: Verify runner contract**

Run:

```bash
pytest tests/test_node_runner.py -q
node --check ocr_runtime/run_ocr.js
```

Expected: PASS and syntax check exits 0.

- [ ] **Step 7: Commit**

```bash
git add ocr_runtime/run_ocr.js optimizer/node_runner.py tests/test_node_runner.py requirements.txt
git commit -m "feat: add OCR node runner contract"
```

---

### Task 6: Evaluation Engine, Failure Classification, And Reports

**Files:**
- Create: `optimizer/evaluation.py`
- Create: `optimizer/reporting.py`
- Create: `tests/test_evaluation.py`
- Create: `tests/test_reporting.py`

- [ ] **Step 1: Add evaluation tests**

Create `tests/test_evaluation.py`:

```python
from optimizer.dataset import Sample
from optimizer.evaluation import EvaluationResult, build_payload, evaluate_samples


class FakeRunner:
    async def run_one(self, payload):
        if payload.image == "missing.png":
            return {"status": 200, "data": [], "imageStatus": ["ok"]}
        return {"status": 200, "data": [{"type": "E-codes", "number": payload.image}], "imageStatus": ["ok"]}


def test_build_payload_uses_card_type_shape():
    sample = Sample(row_number=2, card_image="amazon_aws/card_img_tbay/a.png", origin=10, expected_raw="ABC", scoreable=True)

    payload = build_payload(sample)

    assert payload.image == "amazon_aws/card_img_tbay/a.png"
    assert payload.origin == 10
    assert payload.channel == "TB"
    assert payload.type == "complex"


def test_evaluation_result_extracts_actual_numbers():
    item = EvaluationResult.from_ocr_response(
        Sample(2, "a.png", 0, "A123", True),
        {"status": 200, "data": [{"type": "E-codes", "number": "A-123"}], "imageStatus": ["ok"]},
    )

    assert item.actual_numbers == ["A-123"]
    assert item.row_score.business_correct == 1
    assert item.failure_category == ""


def test_evaluation_classifies_missing_code():
    item = EvaluationResult.from_ocr_response(
        Sample(2, "missing.png", 0, "ABC", True),
        {"status": 200, "data": [], "imageStatus": ["ok"]},
    )

    assert item.failure_category == "missing_code"


async def test_evaluate_samples_uses_concurrency():
    samples = [
        Sample(2, "ABC", 0, "ABC", True),
        Sample(3, "missing.png", 0, "XYZ", True),
    ]

    results = await evaluate_samples(samples, FakeRunner(), concurrency=2)

    assert [r.sample.row_number for r in results] == [2, 3]
    assert results[0].row_score.business_correct == 1
    assert results[1].failure_category == "missing_code"
```

- [ ] **Step 2: Add reporting tests**

Create `tests/test_reporting.py`:

```python
import json

from optimizer.dataset import Sample
from optimizer.evaluation import EvaluationResult
from optimizer.reporting import write_run_artifacts


def test_write_run_artifacts_creates_summary_failures_and_excel(tmp_path):
    sample = Sample(2, "a.png", 0, "ABC", True)
    result = EvaluationResult.from_ocr_response(sample, {"status": 200, "data": [], "imageStatus": ["ok"]})

    write_run_artifacts(
        run_dir=tmp_path,
        phase="dev",
        results=[result],
        prompt_before="old",
        prompt_after="new",
        optimizer_request={"a": 1},
        optimizer_response={"b": 2},
    )

    assert json.loads((tmp_path / "summary.json").read_text())["phase"] == "dev"
    assert (tmp_path / "failures.jsonl").read_text().strip()
    assert (tmp_path / "results.xlsx").exists()
    assert (tmp_path / "prompt.diff").read_text().startswith("--- prompt-before.js")
```

- [ ] **Step 3: Run evaluation/reporting tests and verify failure**

Run:

```bash
pytest tests/test_evaluation.py tests/test_reporting.py -q
```

Expected: FAIL because the modules do not exist.

- [ ] **Step 4: Implement evaluation**

Create `optimizer/evaluation.py` with these public names:

```python
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Sequence

from optimizer.dataset import Sample
from optimizer.node_runner import OcrPayload
from optimizer.scoring import RowScore, score_row


@dataclass(frozen=True)
class EvaluationResult:
    sample: Sample
    ocr_response: dict[str, Any]
    actual_numbers: list[str]
    image_status: str
    row_score: RowScore
    failure_category: str

    @classmethod
    def from_ocr_response(cls, sample: Sample, response: dict[str, Any]) -> "EvaluationResult":
        data = response.get("data") if isinstance(response, dict) else []
        actual_numbers = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("number"):
                    actual_numbers.append(str(item["number"]))
                elif isinstance(item, str) and item:
                    actual_numbers.append(item)
        image_status_values = response.get("imageStatus") if isinstance(response, dict) else []
        image_status = image_status_values[0] if image_status_values else ""
        row_score = score_row(sample.expected_raw, actual_numbers)
        return cls(
            sample=sample,
            ocr_response=response,
            actual_numbers=actual_numbers,
            image_status=str(image_status or ""),
            row_score=row_score,
            failure_category=_failure_category(sample, response, actual_numbers, row_score, str(image_status or "")),
        )


def build_payload(sample: Sample) -> OcrPayload:
    return OcrPayload(image=sample.card_image, origin=sample.origin, channel="TB", type="complex")


def _failure_category(sample: Sample, response: dict[str, Any], actual_numbers: list[str], row_score: RowScore, image_status: str) -> str:
    if not sample.scoreable:
        return ""
    if image_status in {"error-download", "error-small", "error-upload"}:
        return "download_error"
    if image_status == "no-card":
        return "no_card"
    if response.get("status") not in {200, "200"}:
        return "ai_error"
    if row_score.business_total and row_score.business_correct == row_score.business_total:
        return ""
    if not actual_numbers:
        return "missing_code"
    if row_score.unmatched_actual:
        return "extra_code"
    return "wrong_code"


async def evaluate_samples(samples: Sequence[Sample], runner, concurrency: int) -> list[EvaluationResult]:
    semaphore = asyncio.Semaphore(concurrency)

    async def run(sample: Sample) -> EvaluationResult:
        async with semaphore:
            response = await runner.run_one(build_payload(sample))
            return EvaluationResult.from_ocr_response(sample, response)

    return list(await asyncio.gather(*(run(sample) for sample in samples)))
```

- [ ] **Step 5: Implement reporting**

Create `optimizer/reporting.py` with these public functions:

```python
from __future__ import annotations

import difflib
import json
from collections import Counter
from pathlib import Path
from typing import Sequence

from openpyxl import Workbook

from optimizer.evaluation import EvaluationResult
from optimizer.scoring import aggregate_scores


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _summary(phase: str, results: Sequence[EvaluationResult]) -> dict[str, object]:
    score = aggregate_scores(result.row_score for result in results)
    failures = Counter(result.failure_category for result in results if result.failure_category)
    return {
        "phase": phase,
        "samples": len(results),
        "business_total": score.business_total,
        "business_correct": score.business_correct,
        "business_accuracy": score.business_accuracy,
        "strict_correct": score.strict_correct,
        "strict_accuracy": score.strict_accuracy,
        "failure_categories": dict(sorted(failures.items())),
    }


def _write_results_xlsx(path: Path, results: Sequence[EvaluationResult]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "results"
    ws.append(["row_number", "card_image", "origin", "expected", "actual", "business_correct", "business_total", "failure_category", "image_status"])
    for result in results:
        ws.append([
            result.sample.row_number,
            result.sample.card_image,
            result.sample.origin,
            result.sample.expected_raw,
            "\n".join(result.actual_numbers),
            result.row_score.business_correct,
            result.row_score.business_total,
            result.failure_category,
            result.image_status,
        ])
    wb.save(path)


def write_run_artifacts(run_dir: Path, phase: str, results: Sequence[EvaluationResult], prompt_before: str, prompt_after: str, optimizer_request: dict, optimizer_response: dict) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(run_dir / "summary.json", _summary(phase, results))
    _write_json(run_dir / "failure-clusters.json", _summary(phase, results)["failure_categories"])
    _write_json(run_dir / "optimizer-request.json", optimizer_request)
    _write_json(run_dir / "optimizer-response.json", optimizer_response)
    (run_dir / "prompt-before.js").write_text(prompt_before, encoding="utf-8")
    (run_dir / "prompt-after.js").write_text(prompt_after, encoding="utf-8")
    (run_dir / "prompt.diff").write_text(
        "".join(difflib.unified_diff(
            prompt_before.splitlines(True),
            prompt_after.splitlines(True),
            fromfile="prompt-before.js",
            tofile="prompt-after.js",
        )),
        encoding="utf-8",
    )
    with (run_dir / "failures.jsonl").open("w", encoding="utf-8") as handle:
        for result in results:
            if result.failure_category:
                handle.write(json.dumps({
                    "row_number": result.sample.row_number,
                    "card_image": result.sample.card_image,
                    "expected": result.sample.expected_raw,
                    "actual": result.actual_numbers,
                    "failure_category": result.failure_category,
                    "image_status": result.image_status,
                }, ensure_ascii=False) + "\n")
    _write_results_xlsx(run_dir / "results.xlsx", results)
```

- [ ] **Step 6: Verify and commit**

Run:

```bash
pytest tests/test_evaluation.py tests/test_reporting.py -q
```

Expected: PASS.

Commit:

```bash
git add optimizer/evaluation.py optimizer/reporting.py tests/test_evaluation.py tests/test_reporting.py
git commit -m "feat: evaluate OCR samples and write reports"
```

---

### Task 7: Prompt Gate And Optimizer LLM Adapter

**Files:**
- Create: `optimizer/prompt_gate.py`
- Create: `optimizer/llm.py`
- Create: `tests/test_prompt_gate.py`
- Create: `tests/test_llm.py`

- [ ] **Step 1: Add prompt gate tests**

Create `tests/test_prompt_gate.py`:

```python
import pytest

from optimizer.prompt_gate import PromptGateError, validate_prompt_file


def test_validate_prompt_file_accepts_required_exports(tmp_path):
    prompt = tmp_path / "ocr.js"
    prompt.write_text(
        "module.exports={PROMPT_PREFIX:'a',PROMPT_SIMPLE:'b',PROMPT_COMPLEX:'c',PROMPT_COMPLET:'d',PROMPT_DETECT:'e'};",
        encoding="utf-8",
    )

    validate_prompt_file(prompt, node_binary="node")


def test_validate_prompt_file_rejects_missing_export(tmp_path):
    prompt = tmp_path / "ocr.js"
    prompt.write_text("module.exports={PROMPT_PREFIX:'a'};", encoding="utf-8")

    with pytest.raises(PromptGateError, match="missing exports"):
        validate_prompt_file(prompt, node_binary="node")
```

- [ ] **Step 2: Add LLM parser tests**

Create `tests/test_llm.py`:

```python
import pytest

from optimizer.llm import OptimizerProposal, parse_optimizer_response


def test_parse_optimizer_response_extracts_json_object():
    text = '```json\n{"hypothesis":"h","expected_effect":"e","risk":"r","prompt_file":"module.exports={}"}\n```'

    proposal = parse_optimizer_response(text)

    assert proposal == OptimizerProposal("h", "e", "r", "module.exports={}")


def test_parse_optimizer_response_rejects_missing_prompt():
    with pytest.raises(ValueError, match="prompt_file"):
        parse_optimizer_response('{"hypothesis":"h","expected_effect":"e","risk":"r"}')
```

- [ ] **Step 3: Run gate/LLM tests and verify failure**

Run:

```bash
pytest tests/test_prompt_gate.py tests/test_llm.py -q
```

Expected: FAIL because modules do not exist.

- [ ] **Step 4: Implement prompt gate**

Create `optimizer/prompt_gate.py`:

```python
from __future__ import annotations

import json
import subprocess
from pathlib import Path

REQUIRED_EXPORTS = {"PROMPT_PREFIX", "PROMPT_SIMPLE", "PROMPT_COMPLEX", "PROMPT_COMPLET", "PROMPT_DETECT"}


class PromptGateError(RuntimeError):
    pass


def validate_prompt_file(path: str | Path, node_binary: str = "node") -> None:
    prompt_path = Path(path)
    check = subprocess.run([node_binary, "--check", str(prompt_path)], text=True, capture_output=True)
    if check.returncode != 0:
        raise PromptGateError(check.stderr.strip() or "prompt syntax check failed")

    script = (
        "const p=require(process.argv[1]);"
        "process.stdout.write(JSON.stringify(Object.keys(p)));"
    )
    exports = subprocess.run([node_binary, "-e", script, str(prompt_path.resolve())], text=True, capture_output=True)
    if exports.returncode != 0:
        raise PromptGateError(exports.stderr.strip() or "prompt export check failed")
    keys = set(json.loads(exports.stdout))
    missing = sorted(REQUIRED_EXPORTS - keys)
    if missing:
        raise PromptGateError(f"missing exports: {', '.join(missing)}")
```

- [ ] **Step 5: Implement optimizer response parsing and provider calls**

Create `optimizer/llm.py` with response parsing first and provider calls behind one public function:

```python
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OptimizerProposal:
    hypothesis: str
    expected_effect: str
    risk: str
    prompt_file: str


def _json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = "\n".join(line for line in cleaned.splitlines() if not line.strip().startswith("```")).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}") + 1
        data = json.loads(cleaned[start:end])
    if not isinstance(data, dict):
        raise ValueError("optimizer response must be a JSON object")
    return data


def parse_optimizer_response(text: str) -> OptimizerProposal:
    data = _json_object(text)
    required = ["hypothesis", "expected_effect", "risk", "prompt_file"]
    missing = [key for key in required if not isinstance(data.get(key), str) or not data.get(key).strip()]
    if missing:
        raise ValueError(f"optimizer response missing: {', '.join(missing)}")
    return OptimizerProposal(
        hypothesis=data["hypothesis"].strip(),
        expected_effect=data["expected_effect"].strip(),
        risk=data["risk"].strip(),
        prompt_file=data["prompt_file"],
    )


def build_optimizer_messages(current_prompt: str, summary: dict, failure_clusters: dict, failures: list[dict], recent_diffs: list[str]) -> tuple[str, str]:
    system = (
        "You improve a gift card OCR prompt. "
        "Return JSON only with hypothesis, expected_effect, risk, prompt_file. "
        "You may change only the JavaScript prompt file content. "
        "Do not propose changes to scoring, runtime code, datasets, or post-processing."
    )
    user = json.dumps(
        {
            "current_prompt": current_prompt,
            "summary": summary,
            "failure_clusters": failure_clusters,
            "representative_failures": failures[:30],
            "recent_diffs": recent_diffs[-5:],
        },
        ensure_ascii=False,
        indent=2,
    )
    return system, user
```

Add provider-specific network calls after these functions, using existing clients:

```python
def call_optimizer_llm(provider: str, model: str, system: str, user: str) -> OptimizerProposal:
    if provider == "gemini":
        from google import genai
        client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
        response = client.models.generate_content(
            model=model,
            contents=user,
            config=genai.types.GenerateContentConfig(system_instruction=system, temperature=0),
        )
        return parse_optimizer_response(response.text or "")
    if provider == "openai":
        from openai import OpenAI
        response = OpenAI(api_key=os.getenv("OPENAI_API_KEY")).chat.completions.create(
            model=model,
            temperature=0,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        return parse_optimizer_response(response.choices[0].message.content or "")
    if provider == "anthropic":
        import anthropic
        response = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY")).messages.create(
            model=model,
            max_tokens=8192,
            temperature=0,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = response.content[0].text if response.content else ""
        return parse_optimizer_response(text)
    raise ValueError(f"unsupported optimizer provider: {provider}")
```

- [ ] **Step 6: Verify and commit**

Run:

```bash
pytest tests/test_prompt_gate.py tests/test_llm.py -q
```

Expected: PASS.

Commit:

```bash
git add optimizer/prompt_gate.py optimizer/llm.py tests/test_prompt_gate.py tests/test_llm.py
git commit -m "feat: gate OCR prompt optimizer proposals"
```

---

### Task 8: Autorun Loop, Dev/Full Gates, And Prompt Keep/Discard

**Files:**
- Create: `optimizer/git_control.py`
- Create: `optimizer/autorun.py`
- Create: `tests/test_git_control.py`
- Create: `tests/test_autorun.py`

- [ ] **Step 1: Add prompt restore tests**

Create `tests/test_git_control.py`:

```python
from optimizer.git_control import restore_prompt


def test_restore_prompt_uses_saved_content(tmp_path):
    prompt = tmp_path / "ocr.js"
    prompt.write_text("new", encoding="utf-8")

    restore_prompt(prompt, "old")

    assert prompt.read_text(encoding="utf-8") == "old"
```

- [ ] **Step 2: Add stop condition tests**

Create `tests/test_autorun.py`:

```python
from optimizer.autorun import should_stop


def test_stop_when_target_reached():
    assert should_stop(iteration=3, full_accuracy=99.0, target=99.0, plateau_count=0, plateau_window=3, max_iterations=15)


def test_stop_when_plateau_window_reached():
    assert should_stop(iteration=4, full_accuracy=90.0, target=99.0, plateau_count=3, plateau_window=3, max_iterations=15)


def test_stop_when_max_iterations_reached():
    assert should_stop(iteration=15, full_accuracy=90.0, target=99.0, plateau_count=0, plateau_window=3, max_iterations=15)


def test_continue_before_limits():
    assert not should_stop(iteration=2, full_accuracy=90.0, target=99.0, plateau_count=1, plateau_window=3, max_iterations=15)
```

- [ ] **Step 3: Run autorun tests and verify failure**

Run:

```bash
pytest tests/test_git_control.py tests/test_autorun.py -q
```

Expected: FAIL because modules do not exist.

- [ ] **Step 4: Implement git control**

Create `optimizer/git_control.py`:

```python
from __future__ import annotations

import subprocess
from pathlib import Path


def restore_prompt(prompt_path: str | Path, content: str) -> None:
    Path(prompt_path).write_text(content, encoding="utf-8")


def prompt_diff(prompt_path: str | Path) -> str:
    result = subprocess.run(["git", "diff", "--", str(prompt_path)], text=True, capture_output=True)
    return result.stdout


def commit_prompt(prompt_path: str | Path, message: str) -> None:
    subprocess.run(["git", "add", str(prompt_path)], check=True)
    subprocess.run(["git", "commit", "-m", message], check=True)
```

- [ ] **Step 5: Implement autorun stop conditions and CLI skeleton**

Create `optimizer/autorun.py` with these public functions:

```python
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from optimizer.config import OptimizerConfig
from optimizer.dataset import load_dataset, split_samples
from optimizer.evaluation import evaluate_samples
from optimizer.git_control import commit_prompt, restore_prompt
from optimizer.llm import build_optimizer_messages, call_optimizer_llm
from optimizer.node_runner import OcrRunner
from optimizer.prompt_gate import validate_prompt_file
from optimizer.reporting import write_run_artifacts
from optimizer.scoring import aggregate_scores


def should_stop(iteration: int, full_accuracy: float, target: float, plateau_count: int, plateau_window: int, max_iterations: int) -> bool:
    return full_accuracy >= target or plateau_count >= plateau_window or iteration >= max_iterations


def _accuracy(results) -> float:
    return aggregate_scores(result.row_score for result in results).business_accuracy


def _run_dir(base: Path, iteration: int) -> Path:
    name = "run-000-baseline" if iteration == 0 else f"run-{iteration:03d}"
    return base / name


async def run_once(samples, runner, concurrency):
    return await evaluate_samples(samples, runner, concurrency)
```

Then add the CLI body:

```python
async def main_async(args) -> int:
    cfg = OptimizerConfig.from_env()
    samples = load_dataset(args.dataset)
    split = split_samples(samples, cfg.dev_sample_size)
    runner = OcrRunner(cfg.node_binary, cfg.ocr_runner_path)
    experiment_dir = cfg.runs_dir / "card-ocr-prompt-opt"
    best_full_accuracy = -1.0
    plateau_count = 0

    prompt_path = cfg.prompt_path
    validate_prompt_file(prompt_path, cfg.node_binary)
    prompt_before = prompt_path.read_text(encoding="utf-8")

    full_results = await run_once(split.full, runner, cfg.ocr_concurrency)
    best_full_accuracy = _accuracy(full_results)
    write_run_artifacts(_run_dir(experiment_dir, 0), "full", full_results, prompt_before, prompt_before, {}, {})

    for iteration in range(1, cfg.max_iterations + 1):
        if should_stop(iteration - 1, best_full_accuracy, cfg.target_business_accuracy, plateau_count, cfg.plateau_window, cfg.max_iterations):
            break

        current_prompt = prompt_path.read_text(encoding="utf-8")
        summary_path = _run_dir(experiment_dir, iteration - 1) / "summary.json"
        failure_clusters_path = _run_dir(experiment_dir, iteration - 1) / "failure-clusters.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        failure_clusters = json.loads(failure_clusters_path.read_text(encoding="utf-8"))
        system, user = build_optimizer_messages(current_prompt, summary, failure_clusters, [], [])
        proposal = call_optimizer_llm(cfg.optimizer_provider, cfg.optimizer_model, system, user)
        prompt_path.write_text(proposal.prompt_file, encoding="utf-8")
        validate_prompt_file(prompt_path, cfg.node_binary)

        dev_results = await run_once(split.dev, runner, cfg.ocr_concurrency)
        dev_accuracy = _accuracy(dev_results)
        previous_dev_accuracy = summary.get("business_accuracy", 0.0)
        if dev_accuracy <= float(previous_dev_accuracy):
            write_run_artifacts(_run_dir(experiment_dir, iteration), "dev", dev_results, current_prompt, proposal.prompt_file, {"system": system, "user": user}, proposal.__dict__)
            restore_prompt(prompt_path, current_prompt)
            plateau_count += 1
            continue

        full_results = await run_once(split.full, runner, cfg.ocr_concurrency)
        full_accuracy = _accuracy(full_results)
        write_run_artifacts(_run_dir(experiment_dir, iteration), "full", full_results, current_prompt, proposal.prompt_file, {"system": system, "user": user}, proposal.__dict__)
        if full_accuracy > best_full_accuracy:
            best_full_accuracy = full_accuracy
            plateau_count = 0
            commit_prompt(prompt_path, f"prompt: improve card OCR accuracy to {full_accuracy:.2f}%")
        else:
            restore_prompt(prompt_path, current_prompt)
            plateau_count += 1

    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Verify and commit**

Run:

```bash
pytest tests/test_git_control.py tests/test_autorun.py -q
python -m optimizer.autorun --help
```

Expected: tests PASS and CLI help prints `--dataset`.

Commit:

```bash
git add optimizer/git_control.py optimizer/autorun.py tests/test_git_control.py tests/test_autorun.py
git commit -m "feat: automate card OCR prompt optimization loop"
```

---

### Task 9: End-To-End Smoke Test And Operating Documentation

**Files:**
- Create: `tests/test_smoke.py`
- Modify: `README.md`

- [ ] **Step 1: Add smoke test using fake runner and tiny workbook**

Create `tests/test_smoke.py`:

```python
import asyncio

from openpyxl import Workbook

from optimizer.dataset import load_dataset, split_samples
from optimizer.evaluation import evaluate_samples
from optimizer.reporting import write_run_artifacts


class FakeRunner:
    async def run_one(self, payload):
        return {"status": 200, "data": [{"type": "E-codes", "number": payload.image}], "imageStatus": ["ok"]}


def test_tiny_evaluation_writes_artifacts(tmp_path):
    dataset = tmp_path / "cards.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["card_image", "origin", "md5_card_number"])
    ws.append(["ABC123", 0, "ABC123"])
    ws.append(["OIS", 0, "015"])
    wb.save(dataset)

    samples = load_dataset(dataset)
    split = split_samples(samples, dev_size=1, seed=1)
    results = asyncio.run(evaluate_samples(split.full, FakeRunner(), concurrency=2))
    write_run_artifacts(tmp_path / "run", "full", results, "old", "new", {}, {})

    assert (tmp_path / "run" / "summary.json").exists()
    assert (tmp_path / "run" / "results.xlsx").exists()
    assert (tmp_path / "run" / "prompt.diff").exists()
```

- [ ] **Step 2: Run full test suite**

Run:

```bash
pytest -q
```

Expected: PASS.

- [ ] **Step 3: Update README quick start**

Replace the event-extraction quick start with this OCR flow:

```markdown
# Card OCR Prompt Optimizer

This repository runs a self-contained gift-card OCR prompt optimization loop.
Python orchestrates evaluation and prompt keep/discard decisions. The vendored
Node runtime executes the ordinary `code-ocr` OCR path.

## Setup

```bash
pip install -r requirements.txt
cd ocr_runtime && npm install && cd ..
cp .env.example .env
```

Configure `.env` with the local AWS profile, S3 buckets, decrypt salts, AI gateway credentials, and optimizer LLM key.

## Run

```bash
python -m optimizer.autorun --dataset datasets/IT-ST-RZ-TB-500.xlsx
```

Outputs are written under `runs/card-ocr-prompt-opt/`. The optimizer may only replace `prompts/ocr.js`; scoring, dataset, runtime, and git control code are fixed during an experiment.
```

- [ ] **Step 4: Verify documentation command paths**

Run:

```bash
python -m optimizer.autorun --help
node --check prompts/ocr.js
```

Expected: CLI help works and prompt syntax check passes.

- [ ] **Step 5: Commit**

```bash
git add tests/test_smoke.py README.md
git commit -m "docs: document card OCR optimizer workflow"
```

---

## Final Verification

Run all local checks:

```bash
pip install -r requirements.txt
pytest -q
node --check prompts/ocr.js
node --check ocr_runtime/run_ocr.js
node -e "const p=require('./prompts/ocr'); for (const k of ['PROMPT_PREFIX','PROMPT_SIMPLE','PROMPT_COMPLEX','PROMPT_COMPLET','PROMPT_DETECT']) if (!(k in p)) throw new Error(k)"
```

Expected:

- Python tests pass.
- JavaScript syntax checks pass.
- `prompts/ocr.js` exports every required prompt key.
- `git status --short` shows no unstaged implementation files except user-owned local `.env`, datasets, and ignored run artifacts.

Smoke command for the real dataset after credentials are configured:

```bash
AWS_PROFILE=code-ocr-role python -m optimizer.autorun --dataset datasets/IT-ST-RZ-TB-500.xlsx
```

Expected:

- `runs/card-ocr-prompt-opt/run-000-baseline/summary.json` exists.
- `results.xlsx`, `failures.jsonl`, `failure-clusters.json`, and prompt artifacts exist.
- Business accuracy is computed from `md5_card_number` using `card-type` semantics.
- Optimizer proposals are accepted only when `prompts/ocr.js` remains valid JavaScript and full business accuracy improves.

---

## Self-Review

- Spec coverage: dataset Excel contract, ordinary OCR runtime, card-type business scoring, strict diagnostic scoring, optimizer LLM JSON contract, prompt-only boundary, dev/full gates, keep/discard behavior, stop conditions, and run artifacts are each mapped to a task.
- Placeholder scan: no unresolved markers, vague edge-case instructions, or deferred implementation steps remain.
- Type consistency: `Sample`, `OcrPayload`, `EvaluationResult`, `RowScore`, `ScoreSummary`, `OptimizerConfig`, and `OptimizerProposal` names are introduced before use and reused consistently.
- Complexity check: implementation stays intentionally small; Python orchestration is split by responsibility, and the Node side is a source snapshot plus a thin JSON runner.
