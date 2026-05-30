# PRD: Candidate Evaluation Delta Feedback Loop

## Problem Statement

Gift Card Code Recognition Optimization can reject many candidate prompts at the dev gate without giving the next optimizer request precise evidence about what changed. Recent runs showed repeated prompt mutations around secondary strict-format concerns while no baseline business failures improved and some accepted-dev rows regressed. Users need run-local Candidate Evaluation Delta evidence so rejected candidates can inform later proposals without becoming a new baseline or weakening existing accept gates.

## Solution

Add Candidate Evaluation Delta artifacts for dev-evaluated candidates and feed a compressed delta summary into the next optimizer request. The delta compares a candidate prompt against the current Accepted Prompt on the same task and dev evaluation phase, records task-specific primary and secondary metric changes, separates infrastructure failures from prompt-relevant failures, and reports whether declared `target_failures` actually improved, regressed, or stayed unchanged.

Keep the existing acceptance order: prompt gate, dev gate, full gate, then optional regression gate. Candidate Evaluation Delta is feedback evidence only; it must not move the Accepted Prompt baseline, regression baseline, Regression Evaluation Set, or Holdout Evaluation Set.

## User Stories

1. As a prompt optimizer user, I want every dev-evaluated candidate to produce a Candidate Evaluation Delta artifact, so that I can inspect what changed versus the Accepted Prompt.
2. As a prompt optimizer user, I want rejected dev candidates to feed concise row-level evidence into the next optimizer request, so that repeated failures do not produce the same vague prompt changes.
3. As a prompt optimizer user, I want business improvements and regressions separated from strict-only changes, so that optimization stays focused on redeemable code recognition.
4. As a prompt optimizer user, I want infrastructure failures separated from prompt-relevant failures, so that the optimizer does not try to fix download, decrypt, AI, or parse failures through prompt text.
5. As a prompt optimizer user, I want `target_failures_effect` evidence, so that I can see whether the optimizer's declared target failures actually changed.
6. As a prompt optimizer user, I want repeated no-business-learning candidates to stop early with an explicit reason, so that full optimization runs do not waste iterations after the optimizer stops finding business improvements.
7. As a prompt optimizer user, I want each optimization invocation to write to an isolated Optimization Run Session, so that stale artifacts from an earlier run cannot be mistaken for current evidence.
8. As a prompt optimizer maintainer, I want the delta structure to support both code and type tasks, so that the shared autorun loop does not grow a code-only feedback path.
9. As a reviewer, I want stop reasons written as artifacts, so that run completion can be audited without reconstructing state from logs.

## Implementation Decisions

- Use **Candidate Evaluation Delta** as the domain term for per-row evaluation changes between a candidate prompt and the current Accepted Prompt for the same task and evaluation phase.
- Write `dev-delta.json` for every candidate that reaches dev evaluation, including both dev-rejected and dev-passing candidates.
- Store full row details in `dev-delta.json`; only feed a compressed summary into the optimizer prompt.
- Compare candidates only against the current Accepted Prompt on the same Dev Evaluation Set. Rejected candidates may inform future proposals but never become the baseline.
- Use task-neutral top-level metric fields such as `primary_metric` and `secondary_metric`, with task-specific row details.
- For code tasks, Business Code Match is the primary metric and Strict Code Match is secondary feedback.
- For type tasks, type accuracy and not-evaluable changes are task-specific primary feedback; code-only categories such as `extra_code`, `wrong_code`, and `no_card` must not be reused for type.
- For code rows, classify candidate changes into `improved_business_rows`, `regressed_business_rows`, `persistent_business_failure_rows`, `strict_only_changed_rows`, and `infra_failure_rows`.
- Preserve original failure categories in row details. `no_card` remains a prompt-relevant business failure; infrastructure categories are separated.
- Treat `extra_code` as secondary feedback when Business Code Match is already correct. It must not displace primary business failures unless a strict optimization mode is explicitly introduced later.
- Record `target_failures_effect` as run evidence without adding strong semantic validation to optimizer response parsing.
- Mark target declarations that only name secondary or infrastructure failures with `target_priority_mismatch`, but do not fail parsing or prompt validation for that alone.
- Continue to pass `recent_diffs` as auxiliary context, but make Candidate Evaluation Delta summary the primary optimizer feedback after dev-evaluated rejects.
- Add `no_business_learning_count` separately from the existing plateau count. Count only dev-evaluated candidates with no improved business rows.
- Reset `no_business_learning_count` when a dev-evaluated candidate has any business improvement, even if the candidate is still rejected because of offsetting regressions or no net score gain.
- Stop early with reason `no_business_learning` when repeated dev-evaluated candidates show no Business Code Match improvements.
- Configure the no-business-learning stop window through `NO_BUSINESS_LEARNING_WINDOW`, defaulting to `3`. Do not add a new CLI flag for this first implementation.
- Write each optimizer invocation to a new Optimization Run Session under the task's run root, so repeated invocations do not overwrite or mix artifacts.
- Keep `RUNS_DIR` as the root for all run artifacts. The task run root remains `RUNS_DIR/card-ocr-prompt-opt-{task}`, and each Optimization Run Session is created under that task run root.
- Apply Optimization Run Session isolation to smoke and full tasks. Smoke sessions may contain only `run-000-baseline` and `stop.json`.
- Name Optimization Run Session directories with local `Asia/Shanghai` wall-clock time in `YYYY-MM-DD_HH-MM-SS` format.
- If a session directory already exists for the same second, append `-02`, then `-03`, and continue incrementing until an unused directory name is found.
- Write `stop.json` at the Optimization Run Session root when the optimization loop stops. Include reason, task, iteration, metric state, plateau count, no-business-learning count, `last_run_dir`, and `last_phase`.
- Maintain a lightweight `latest.json` pointer under the task's run root that identifies the most recent Optimization Run Session using a relative `session_dir` and relative repository path, not an absolute filesystem path.
- Do not create a `latest/` symlink or copy of the latest session directory.
- Do not migrate existing flat `run-*` directories into a session. Future invocations must use session directories, and `latest.json` should only point to a session created by the new workflow.
- When the optimizer exits, print the relative run session path and stop reason in concise console output.
- When `MAX_ITERATIONS=0`, write `stop.json` with reason `max_iterations`, `iteration` set to `0`, `last_run_dir` set to `run-000-baseline`, and `last_phase` set to `full`.
- Keep stop reason priority as `target_reached`, `no_business_learning`, `plateau`, then `max_iterations`.

## Testing Decisions

- Autorun tests should verify that dev-evaluated candidates write `dev-delta.json`.
- Autorun tests should verify that dev-rejected candidates restore the prompt and feed delta summary into the next optimizer request.
- Autorun tests should verify that accepted-dev baseline updates only after candidate acceptance.
- Delta tests should cover improved business rows, regressed business rows, persistent business failures, strict-only changes, infrastructure failures, and partial multi-code row regressions.
- LLM message tests should verify that Candidate Evaluation Delta summary is prioritized over recent diffs.
- Tests should verify `target_failures_effect`, including row-number targets, category targets, ignored infrastructure targets, and `target_priority_mismatch`.
- Stop-condition tests should verify `no_business_learning` counting, reset behavior, priority against plateau and max iterations, and `stop.json` contents.
- Session tests should verify that separate optimizer invocations write to separate Optimization Run Sessions and update `latest.json`.
- Existing regression-gate tests remain responsible for full/regression accept behavior and should not be folded into Candidate Evaluation Delta tests.
- Verification should include `uv run pytest -q`.

## Out of Scope

- Changing OCR runtime request behavior, provider routing, S3, decrypt, image download, AI gateway, or deployment behavior.
- Automatically adding rows to a Regression Evaluation Set.
- Implementing Holdout Evaluation Set input, scheduling, or gate behavior.
- Adding a global append-only experiment log.
- Changing Gift Card Code Recognition Optimization scoring semantics.
- Introducing a strict optimization mode.
- Adding a UI.
