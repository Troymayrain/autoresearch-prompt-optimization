# Card OCR Prompt Optimizer

This repository runs a self-contained gift-card OCR prompt optimization loop.
Python orchestrates dataset loading, OCR evaluation, scoring, reporting,
optimizer LLM calls, and prompt keep/discard decisions. The vendored Node
runtime in `ocr_runtime/` executes the ordinary `code-ocr` OCR path.

Only `prompts/ocr.js` is allowed to change during an experiment. Scoring,
dataset loading, OCR runtime code, and git control code stay fixed.

## Setup

```bash
uv sync
cd ocr_runtime && npm install && cd ..
cp .env.example .env
```

Configure `.env` with the local AWS profile, S3 buckets, decrypt salts, AI
gateway credentials, and optimizer LLM key.

Code optimization dataset columns:

- `card_image`
- `origin`
- `md5_card_number`

`md5_card_number` can contain multiple accepted card numbers separated by newlines.

Type optimization dataset columns:

- `card_image`
- `origin`
- `golden_type`

`golden_type` is only physical versus electronic card form. Valid values are
`Physics` and `E-codes`, repeated once per image in the row, such as
`PhysicsPhysics` for two physical-card images. It does not mean `cardType`,
brand, country, currency, or denomination.

## Run

```bash
uv run poe code-smoke
uv run poe code-full
uv run poe type-smoke
uv run poe type-full
```

Command datasets:

- `code-smoke`: `datasets/IT-ST-RZ(TB)_1.xlsx`
- `code-full`: `datasets/IT-ST-RZ(TB)_500.xlsx`
- `type-smoke`: `datasets/type_ocr_1.xlsx`
- `type-full`: `datasets/type_ocr_500.xlsx`

Outputs are written under `runs/card-ocr-prompt-opt-code/` or
`runs/card-ocr-prompt-opt-type/`.

Each iteration:

1. evaluates the accepted prompt,
2. asks the optimizer LLM to rewrite `prompts/ocr.js` from failure reports,
3. validates the generated JavaScript prompt file,
4. runs the dev split,
5. runs the full dataset only if dev accuracy improves,
6. commits the prompt only if the selected full metric improves,
7. restores the previous prompt content otherwise.

Code business accuracy follows the `card-type` matching rule: exact match
first, then expected-order `includes` matching, with each actual OCR code
consumed at most once. Type accuracy concatenates OCR `type` values in image
order and counts a row correct when the prediction contains the row's
`golden_type`.

Infrastructure failures such as S3 download, decrypt, AI, and parse errors are
excluded from the selected accuracy denominator. Type rows without OCR `type`
values are reported as `not_evaluable`; type optimization is not allowed to fix
detection, code extraction, `cardType`, country, currency, denomination, or
number output.

## Useful Checks

```bash
uv run pytest -q
cd ocr_runtime && npm run check && cd ..
uv run python -m optimizer.autorun --help
node --check prompts/ocr.js
```

## Runtime Layout

```text
optimizer/          Python orchestration, scoring, reporting, LLM, keep/discard
ocr_runtime/        vendored Node OCR runtime copied from code-ocr
prompts/ocr.js      only prompt file the optimizer may replace
datasets/           local Excel datasets, ignored by git
runs/               generated experiment artifacts, ignored by git
```

Mutation boundaries:

- `code`: may change code extraction, number output, and code-candidate
  detection prompt rules.
- `type`: may change only physical-versus-electronic `type` rules in
  `PROMPT_COMPLEX` and `PROMPT_COMPLET`.
- Both tasks must leave OCR runtime behavior, metadata fields, dataset parsing,
  scoring, reporting, and git control code unchanged.
