# Card OCR Prompt Optimizer

This repository runs a self-contained gift-card OCR prompt optimization loop.
Python orchestrates dataset loading, OCR evaluation, scoring, reporting,
optimizer LLM calls, and prompt keep/discard decisions. The vendored Node
runtime in `ocr_runtime/` executes the ordinary `code-ocr` OCR path.

Only `prompts/ocr.js` is allowed to change during an experiment. Scoring,
dataset loading, OCR runtime code, and git control code stay fixed.

## Setup

```bash
python3.11 -m pip install -r requirements.txt
cd ocr_runtime && npm install && cd ..
cp .env.example .env
```

Configure `.env` with the local AWS profile, S3 buckets, decrypt salts, AI
gateway credentials, and optimizer LLM key.

Required dataset columns:

- `card_image`
- `origin`
- `md5_card_number`

`md5_card_number` can contain multiple accepted card numbers separated by newlines.

## Run

```bash
AWS_PROFILE=code-ocr-role python3.11 -m optimizer.autorun --dataset datasets/IT-ST-RZ-TB-500.xlsx
```

Outputs are written under `runs/card-ocr-prompt-opt/`.

Each iteration:

1. evaluates the accepted prompt,
2. asks the optimizer LLM to rewrite `prompts/ocr.js` from failure reports,
3. validates the generated JavaScript prompt file,
4. runs the dev split,
5. runs the full dataset only if dev accuracy improves,
6. commits the prompt only if full business accuracy improves,
7. restores the previous prompt content otherwise.

Business accuracy follows the `card-type` matching rule: exact match first,
then expected-order `includes` matching, with each actual OCR code consumed at
most once. Infrastructure failures such as S3 download, decrypt, AI, and parse
errors are excluded from the prompt accuracy denominator.

## Useful Checks

```bash
pytest -q
cd ocr_runtime && npm run check && cd ..
python3.11 -m optimizer.autorun --help
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
