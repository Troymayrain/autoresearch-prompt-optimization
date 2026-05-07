# Card OCR Prompt Optimizer Design

## Context

This project currently implements an autoresearch-style prompt optimization loop for text event extraction. The new target is a self-contained gift card OCR prompt optimization system for business card image samples.

The system must adapt the relationship previously observed between `card-type` and `code-ocr`:

- `card-type` defines the business-facing Excel input and accuracy semantics.
- `code-ocr` ordinary OCR defines the production image recognition path.
- This project will own the optimization loop and run it without runtime dependency on external repository paths.

The main input dataset is an Excel file with three columns:

```text
card_image
origin
md5_card_number
```

`md5_card_number` is the human-labeled golden answer. One row may contain multiple correct card codes, separated by newlines.

## Goals

- Run the ordinary OCR path for the labeled card image dataset.
- Score each run using the same business accuracy semantics as `card-type`.
- Let an optimizer LLM analyze failed samples and modify only the OCR prompt.
- Keep prompt changes only when full-dataset business accuracy improves.
- Discard regressions automatically.
- Stop when the target business accuracy or plateau limits are reached.
- Keep all runtime code needed for evaluation inside this repository.

## Non-Goals

- Do not modify the golden dataset during optimization.
- Do not let the optimizer LLM modify scoring, matching, post-processing, or OCR runtime code.
- Do not require a runtime `CODE_OCR_DIR` or any cross-repository path configuration.
- Do not deploy Lambda for each experiment.
- Do not treat infrastructure failures as prompt misses.

## Architecture

The project will become a self-contained OCR prompt optimization workspace:

```text
autoresearch-prompt-optimization/
├── ocr_runtime/          # vendored Node OCR runtime derived from code-ocr ordinary OCR
├── prompts/ocr.js        # initial copy of code-ocr/prompts/ocr.js; optimizer edits only this file
├── optimizer/            # Python orchestration, scoring, reports, LLM prompt editing, keep/discard
├── datasets/             # input Excel files
├── runs/                 # per-run audit artifacts
└── docs/                 # design and operating notes
```

Control remains in Python. OCR execution stays in Node to avoid rewriting production OCR behavior in Python.

```text
Excel dataset
  -> Python optimizer loads and splits samples
  -> Python builds card-type-style payloads
  -> Node OCR runtime executes local ordinary OCR
  -> Python scores business and strict accuracy
  -> Optimizer LLM proposes prompt-only changes
  -> Python validates prompt syntax and exports
  -> Python runs dev/full gates
  -> Git keep/discard records the result
```

The vendored OCR runtime is a local snapshot of the ordinary `code-ocr` OCR path. It should include the minimum modules needed for local evaluation:

```text
ocr_runtime/
├── index.js
├── handler-ocr.js
├── shared.js
├── utils.js
├── ai-provider.js
├── log-sanitizer.js
├── prompts/
│   └── ocr.js
└── package.json
```

The runtime snapshot should record the source `code-ocr` commit so future syncs are explicit.

## OCR Request Contract

The Python optimizer constructs payloads matching `card-type` ordinary OCR calls:

```json
{
  "image": "amazon_aws/card_img_tbay/...",
  "origin": 0,
  "channel": "TB",
  "type": "complex"
}
```

The Node runner invokes the ordinary OCR request handler and returns structured JSON with at least:

```json
{
  "status": 200,
  "data": [
    { "type": "Physics", "number": "..." }
  ],
  "imageStatus": ["ok"],
  "ai": {
    "name": "...",
    "model": "...",
    "providers": []
  }
}
```

Failures must be returned as structured JSON, not mixed into stdout logs.

## Configuration

Runtime configuration is read from `.env` or process environment.

```env
AWS_PROFILE=code-ocr-role
S3_READ_REGION=ap-east-1
S3_BUCKET_TB_GX=gx-card-pro
S3_BUCKET_TB_TBAY=tbay-card-prod
USE_LOCAL_IMAGES=false
ENABLE_S3_UPLOAD=false

DEC_SALT_TB=...
DEC_SALT_CG=...
DEC_SALT_TM=...

AI_PROVIDER=vertex-account
GOOGLE_SA_KEY_SSM_PARAM=/code-ocr/google-service-account-key
SSM_REGION=ap-east-1

OCR_CONCURRENCY=10
DELAY=0

DEV_SAMPLE_SIZE=150
TARGET_BUSINESS_ACCURACY=99.0
PLATEAU_WINDOW=3
MAX_ITERATIONS=15
NO_CARD_FAILURE_THRESHOLD=5.0
```

The target OCR AI provider keeps the `code-ocr` provider shape so local evaluation stays close to production. The optimizer LLM provider is separately configurable and can be OpenAI, Anthropic, Gemini, or another supported backend selected by `.env`.

## Dataset Handling

The Excel loader must enforce these required columns:

```text
card_image
origin
md5_card_number
```

Rules:

- Empty `card_image` rows are invalid.
- `origin` is converted to an integer and passed unchanged to OCR.
- Empty `md5_card_number` rows are skipped for accuracy scoring.
- Multiple expected card codes are split by `\r?\n`.
- Dataset split is deterministic with a fixed seed.
- `dev` defaults to 150 rows.
- `full` is all valid rows.

## Accuracy Semantics

The primary keep/discard metric is business accuracy aligned with `card-type/accuracy.js`.

Business normalization:

- Convert to string.
- Trim.
- Remove whitespace, newlines, tabs, vertical tabs, form feeds, non-breaking spaces, full-width spaces, and hyphens.
- Convert to uppercase.
- Replace `O` with `0`.
- Replace `I` with `1`.
- Replace `S` with `5`.

Business matching:

- Split expected and actual cells by newline.
- Filter empty normalized entries.
- First pass: normalized equality.
- Second pass: expected code contained in actual code.
- Each actual code can be consumed only once.
- Matching does not require positional alignment.
- Includes ambiguity follows `card-type` expected-order greedy tie-break; it does not do maximum matching.

Strict accuracy is diagnostic only:

- Remove whitespace and hyphens.
- Convert to uppercase.
- Do not replace `O/I/S`.

Keep/discard and stop decisions use business accuracy, not strict accuracy.

## Failure Classification

Each failed row should get a stable failure category:

```text
missing_code       expected exists, actual has no matching code
wrong_code         actual exists but does not match expected
extra_code         actual has additional unmatched codes
wrong_type         number matches but type is wrong, if type scoring is enabled
no_card            detect returned no-card
download_error     S3 or image read failed
decrypt_error      image decryption failed
ai_error           AI provider failed
parse_error        OCR returned invalid JSON or unexpected schema
```

Infrastructure failures are counted separately. They must not be silently treated as prompt quality failures.

## Optimization Loop

Each run follows this sequence:

1. Validate `prompts/ocr.js`.
2. Run the `dev` set.
3. Generate run artifacts.
4. If `dev business_accuracy` does not improve, do not run `full`.
5. If `dev business_accuracy` improves, run `full`.
6. If `full business_accuracy` improves, commit the prompt change and mark the run `keep`.
7. If `full business_accuracy` does not improve, discard the prompt change and mark the run `discard`.
8. Send failure summaries to the optimizer LLM.
9. Optimizer LLM proposes the next complete `prompts/ocr.js`.
10. Repeat until stop conditions trigger.

Stop when any condition is true:

- `full business_accuracy >= TARGET_BUSINESS_ACCURACY`
- `PLATEAU_WINDOW` consecutive full runs have no business accuracy improvement
- `MAX_ITERATIONS` is reached

## Optimizer LLM Contract

The optimizer LLM receives:

- Current prompt file.
- Latest summary metrics.
- Failure clusters.
- Representative failed samples.
- Recent prompt diffs.
- Prior learnings.

The optimizer LLM must output structured JSON:

```json
{
  "hypothesis": "What this change is meant to fix",
  "expected_effect": "Which failures should improve",
  "risk": "Which existing rules might be harmed",
  "prompt_file": "Complete replacement content for prompts/ocr.js"
}
```

The implementation should prefer full-file replacement over free-form diff application. Diffs are still saved for audit after replacement.

## Prompt Modification Boundary

The optimizer LLM may modify only:

```text
prompts/ocr.js
```

It must not modify:

- OCR runtime code
- Python scoring code
- Excel loader
- Dataset files
- Matching/post-processing logic
- Git control logic

Prompt gate checks:

- `node --check prompts/ocr.js`
- Required exports exist:
  - `PROMPT_PREFIX`
  - `PROMPT_SIMPLE`
  - `PROMPT_COMPLEX`
  - `PROMPT_COMPLET`

Detect prompt policy:

- Default optimization focuses on recognize prompts.
- Detect prompt may be opened only if `no_card` failures exceed `NO_CARD_FAILURE_THRESHOLD`.
- Even then, only prompt text may change.

## Run Artifacts

Each experiment run stores complete audit data:

```text
runs/
└── YYYY-MM-DD-card-ocr-prompt-opt/
    ├── run-000-baseline/
    ├── run-001/
    ├── run-002/
    └── final-summary.json
```

Each run directory includes:

```text
summary.json
results.xlsx
failures.jsonl
failure-clusters.json
optimizer-request.json
optimizer-response.json
prompt-before.js
prompt-after.js
prompt.diff
run.log
```

Reports must not include AWS secret keys, SSM parameter values, AI provider keys, decrypted raw image bytes, or full base64 image payloads.

## Testing Strategy

### Scoring Unit Tests

Cover:

- Multi-code golden answers split by newline.
- Order-independent matching.
- One actual code consumed only once.
- Business `O/I/S` normalization.
- Strict versus business accuracy differences.
- Empty expected rows skipped.
- `no-card` and `error-*` status classification.

### Excel Loader Tests

Cover:

- Required column validation.
- `origin` numeric conversion.
- Empty golden answer skip behavior.
- Newline-preserving golden answer parsing.

### Node Runner Contract Tests

Cover:

- Python-to-Node payload passing.
- JSON-only stdout contract.
- Stable success schema.
- Stable structured error schema.

### Prompt Gate Tests

Cover:

- `node --check prompts/ocr.js`.
- Required exports.
- Rejection when optimizer tries to alter non-prompt files.

### End-to-End Smoke Test

Use a tiny Excel or mock runner with two or three rows to verify:

- Run directory creation.
- Summary generation.
- Failure artifact generation.
- Prompt diff generation.
- Keep/discard path execution.

## Acceptance Criteria

The system is acceptable when:

- A single command can start a complete experiment:

```bash
python -m optimizer.autorun --dataset datasets/IT-ST-RZ-TB-500.xlsx
```

- Baseline evaluation produces business accuracy, strict accuracy, failures, and result Excel.
- Optimizer LLM can only modify `prompts/ocr.js`.
- Dev improvement is required before full evaluation.
- Full business accuracy improvement is required before keep.
- Regressions are automatically discarded.
- Stop conditions work for target accuracy, plateau, and max iterations.
- Final output includes the optimized prompt file and diff suitable for syncing back to `code-ocr`.

## Risks And Controls

| Risk | Control |
| --- | --- |
| Vendored OCR runtime drifts from `code-ocr` | Record source commit and update runtime intentionally |
| Optimizer LLM learns to game scoring | Freeze scoring, matching, dataset, and runtime code |
| Prompt overfits 500 samples | Use dev/full gating and preserve strict diagnostics |
| Infrastructure failures pollute prompt metrics | Classify download, decrypt, AI, and parse failures separately |
| Prompt file becomes invalid JS | Run `node --check` and export validation before OCR |
| Secrets leak into artifacts | Redact credentials, SSM values, base64 images, and raw decrypted image bytes |

## Implementation Handoff

After this design is approved, implementation planning should decompose work into:

1. Vendor OCR runtime snapshot and prompt baseline.
2. Excel loader and deterministic dataset split.
3. Node runner contract.
4. Business/strict scoring library.
5. Evaluation runner and report generation.
6. Optimizer LLM adapter and prompt replacement gate.
7. Git keep/discard loop and stop conditions.
8. Tests and smoke workflow.
