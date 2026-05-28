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

# REVIEW-02

Verdict: `gaps_found`

Scope reviewed: `e334302..40957b8` against
`docs/prd/task-aware-code-and-type-prompt-optimization.md`, the execution CSV,
and the `REVIEW-01` follow-up fixes.

Findings:

- P1: Type-task prompt gate allows `PROMPT_COMPLEX` and `PROMPT_COMPLET` type
  sections to diverge. The PRD requires type rules in both prompts to stay
  aligned, and runtime evaluation exercises the complex payload path only, so
  complete-output behavior can drift without being caught.

Evidence checked:

- `uv run pytest -q` passed with 107 tests.
- `node --check prompts/ocr.js` passed.
- `npm run check` in `ocr_runtime` passed.
- `uv run poe --help` listed `code-smoke`, `code-full`, `type-smoke`, and
  `type-full`.
- `git show HEAD:docs/prd/task-aware-code-and-type-prompt-optimization.md`
  passed.
- `git diff --stat e334302..40957b8`
- `optimizer/node_runner.py`
- `optimizer/prompt_gate.py`
- `optimizer/reporting.py`
- `optimizer/dataset.py`
- `optimizer/scoring.py`
- `optimizer/evaluation.py`
- `optimizer/autorun.py`
- `optimizer/llm.py`
- Prompt gate, reporting, scoring, evaluation, autorun, command contract, and
  dataset tests.

Closed from REVIEW-01: `FOLLOWUP-01`, `FOLLOWUP-02`, `FOLLOWUP-03`, and
`FOLLOWUP-04`.

Follow-up rows added: `FOLLOWUP-05` and `REVIEW-03`.

# REVIEW-03

Verdict: `gaps_found`

Scope reviewed: `e334302..955ce2e` against
`docs/prd/task-aware-code-and-type-prompt-optimization.md`, the execution CSV,
and the `REVIEW-01` / `REVIEW-02` follow-up fixes.

Findings:

- P2: `FOLLOWUP-05` CSV evidence records `uv run pytest -q passed 109 tests`,
  but a clean `955ce2e` snapshot reports `107 passed`. Functional validation is
  green, but the evidence count is not consistent with committed files.

Evidence checked:

- Clean `955ce2e` snapshot `uv run pytest -q` passed with 107 tests.
- `node --check prompts/ocr.js` passed.
- `npm run check` in `ocr_runtime` passed.
- `uv run poe --help` listed `code-smoke`, `code-full`, `type-smoke`, and
  `type-full`.
- `git show 955ce2e:docs/prd/task-aware-code-and-type-prompt-optimization.md`
  passed.
- Manual counterexamples confirmed the type gate rejects complex-only and
  complete-only type-rule changes, while accepting aligned type-rule updates.
- `optimizer/prompt_gate.py`
- `tests/test_prompt_gate.py`

Closed functionally: `FOLLOWUP-01`, `FOLLOWUP-02`, `FOLLOWUP-03`,
`FOLLOWUP-04`, and `FOLLOWUP-05`.

Follow-up rows added: `FOLLOWUP-06` and `REVIEW-04`.
