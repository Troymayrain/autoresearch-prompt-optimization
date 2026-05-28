# REVIEW-01

Verdict: `gaps_found`

Scope reviewed: `e334302..2893de4` against
`docs/prd/task-aware-code-and-type-prompt-optimization.md` and the execution CSV.

Findings:

- P0: Clean `uv run pytest -q` failed at `2893de4` because `OcrPayload` did not
  expose the `mode` field asserted by `tests/test_evaluation.py`.
- P1: Code-task prompt gate rejected all `PROMPT_COMPLEX` and `PROMPT_COMPLET`
  changes, which also blocks legitimate code extraction and number output prompt
  changes allowed by the PRD.
- P2: Type `results.xlsx` still used code metric columns
  `business_correct` and `business_total`.
- P2: The CSV referenced `docs/prd/task-aware-code-and-type-prompt-optimization.md`,
  but that source PRD was not committed at the reviewed head.

Evidence checked:

- `git diff --stat e334302..2893de4`
- `pyproject.toml`
- `optimizer/scoring.py`
- `optimizer/evaluation.py`
- `optimizer/autorun.py`
- `optimizer/prompt_gate.py`
- `optimizer/reporting.py`
- `README.md`
- `uv run pytest -q`
- `node --check prompts/ocr.js`
- `npm run check` in `ocr_runtime`

Follow-up rows added: `FOLLOWUP-01`, `FOLLOWUP-02`, `FOLLOWUP-03`,
`FOLLOWUP-04`, and `REVIEW-02`.
