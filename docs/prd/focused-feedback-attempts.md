# PRD: Focused Feedback Attempts

## Problem Statement

Gift Card Code Recognition Optimization now uses Dev Evaluation Set row-level feedback instead of Full Evaluation Set row targets, but recent runs still show no Business Code Match learning. The optimizer receives correct target rows, yet it mutates the prompt across multiple unrelated Feedback Failure Groups in one proposal, producing broad rule additions that leave targeted rows unchanged and introduce regressions in previously passing rows.

Users need the optimizer workflow to isolate strategy attempts, preserve clear Candidate Evaluation Delta attribution, avoid repeating failed prompt changes in the same Optimization Run Session, and produce human-reviewable evidence for failures that may require visual inspection or label correction before more prompt optimization.

## Solution

Introduce Focused Feedback Attempts. Each optimizer proposal targets exactly one primary Feedback Failure Group from the Optimizer Feedback Set. Other groups may remain background evidence, but only the focused group may provide active row-level targets.

Add run-local Failed Strategy Memory so an Optimization Run Session does not repeat a strategy that left targeted rows unchanged or caused regressions. Enhance feedback artifacts with enough evidence for human review, and write a review workbook for manual triage before treating hard rows as prompt-solvable.

## User Stories

1. As a prompt optimizer user, I want each optimizer proposal to target one Feedback Failure Group, so that I can understand which rule change caused the next Candidate Evaluation Delta.
2. As a prompt optimizer user, I want the optimizer to avoid mixing no-card, wrong-number, and OCR-confusion changes in one proposal, so that regressions are easier to attribute.
3. As a prompt optimizer user, I want `target_failures` to come only from the active focused group, so that row-level delta evidence remains closed-loop and auditable.
4. As a prompt optimizer user, I want other primary groups kept as background evidence, so that the optimizer understands the wider failure shape without changing too many things at once.
5. As a prompt optimizer user, I want Secondary Code Cleanliness Signal groups excluded from primary optimization, so that strict cleanup does not displace Business Code Match failures.
6. As a prompt optimizer user, I want the workflow to prefer `wrong_code_selected_non_redeemable_number` before no-card failures, so that the optimizer starts with cases most likely to be prompt-controllable.
7. As a prompt optimizer user, I want each primary Feedback Failure Group tried at most once when it produces no improvement, so that repeated no-op prompt wording does not waste iterations.
8. As a prompt optimizer user, I want a group that improves but is not accepted to be eligible for one follow-up attempt, so that a partially useful strategy can be refined without opening an infinite loop.
9. As a prompt optimizer user, I want failed strategies recorded in the run artifacts, so that I can see what was tried and why it should not be repeated in the same session.
10. As a prompt optimizer user, I want failed strategy evidence to include target rows and regressed rows, so that I can inspect the actual business impact.
11. As a prompt optimizer user, I want failed strategy evidence to include a concise prompt-diff summary, so that I can identify repeated strategy patterns without reading a full diff.
12. As a prompt optimizer user, I want the optimizer request to receive Failed Strategy Memory, so that the model is explicitly told which strategies not to repeat.
13. As a prompt optimizer user, I want the workflow to stop only after all primary groups have been attempted without Business Code Match learning, so that one failed group does not hide potential improvement in another group.
14. As a prompt optimizer user, I want the stop reason to remain auditable, so that no-business-learning still has a clear artifact trail.
15. As a prompt optimizer user, I want feedback examples to include `origin` and `card_image`, so that I can manually inspect whether the labeled code is actually visible.
16. As a prompt optimizer user, I want a review workbook for feedback failures, so that I can triage hard rows outside the optimizer loop.
17. As a prompt optimizer user, I want the review workbook to show expected and actual values, so that I can separate model errors from possible golden-label errors.
18. As a prompt optimizer user, I want the review workbook to include empty human decision fields, so that a reviewer can mark whether a row is prompt-solvable, label-suspect, image-unreadable, or regression-worthy.
19. As a prompt optimizer user, I want review artifacts to be run-local, so that manual triage stays tied to the evidence that produced it.
20. As a prompt optimizer maintainer, I want group selection logic isolated behind a small interface, so that optimizer scheduling does not spread through the autorun loop.
21. As a prompt optimizer maintainer, I want Failed Strategy Memory isolated behind a small interface, so that strategy outcome classification can be tested without running OCR.
22. As a prompt optimizer maintainer, I want review artifact writing to stay in reporting code, so that the optimizer loop does not own workbook formatting.
23. As a prompt optimizer maintainer, I want Candidate Evaluation Delta to remain the source of truth for attempt outcomes, so that failed strategy classification does not invent a second metric system.
24. As a prompt optimizer maintainer, I want Focused Feedback Attempts to support code and future task-specific groups without hard-coding unrelated task semantics into shared logic.
25. As a reviewer, I want tests that prove only one group is active per optimizer request, so that broad multi-group prompt changes cannot silently return.
26. As a reviewer, I want tests that prove focused group keys expand to dev row targets before delta comparison, so that `row_not_found` does not reappear.
27. As a reviewer, I want tests that prove failed strategies suppress repeated attempts in the same session, so that no-business-learning runs do not retry the same ineffective strategy.
28. As a reviewer, I want tests that prove review workbooks include all primary and secondary feedback rows, so that manual triage does not lose evidence.
29. As a reviewer, I want tests that prove full-set row failures remain background-only, so that Dev Evaluation Set remains the Optimizer Feedback Set.
30. As a reviewer, I want verification to include the full Python test suite, so that focused scheduling does not break existing regression gates or delta artifacts.

## Implementation Decisions

- Use **Focused Feedback Attempt** as the domain term for one optimizer proposal focused on exactly one primary Feedback Failure Group.
- Use **Failed Strategy Memory** as the domain term for run-local evidence that a strategy for a Feedback Failure Group failed to improve targeted rows or caused regressions.
- Keep Failed Strategy Memory run-local. Do not create cross-session strategy memory, because prompt version, model version, dataset version, and evaluation evidence may drift.
- Keep Focused Feedback Attempts as the default automatic optimization behavior for Gift Card Code Recognition Optimization.
- A focused attempt has one active primary group. Other primary groups remain optimizer background evidence and cannot provide row-level `target_failures`.
- Secondary groups are not eligible for active automatic primary optimization while Business Code Match failures remain.
- Group selection order is fixed for the first implementation: selected non-redeemable number, OCR confusion, no-card false negative, then any remaining primary groups.
- If a focused group produces unchanged target rows or regressions, record a Failed Strategy Memory entry and do not retry that group in the same session.
- If a focused group produces any Business Code Match improvement but is not accepted, allow one additional focused attempt for that same group.
- Stop with no-business-learning only when every primary group has been attempted without Business Code Match improvement, or when no eligible focused group remains.
- Keep existing target reached, plateau, and max-iteration stop mechanisms.
- Candidate Evaluation Delta remains the source of attempt outcome classification.
- The focused group key may be returned by the optimizer, but it must be expanded to row targets from the active Dev Evaluation Set group before delta comparison.
- Optimizer requests should expose the active focused group as a separate contract, not by trimming the whole feedback artifact into an ambiguous list.
- Optimizer requests should include run-local Failed Strategy Memory so the optimizer is told what not to repeat.
- Optimizer requests should describe inactive primary groups as background evidence only.
- `feedback-failures` examples should include `origin` and `card_image` in addition to row number, expected value, actual value, failure category, and image status.
- Add a review workbook artifact for feedback failures. The workbook is for manual triage, not automatic dataset mutation.
- The review workbook should include `group_key`, `row_number`, `origin`, `card_image`, `expected`, `accepted_actual`, `last_candidate_actual`, `failure_category`, `review_decision`, and `review_notes`.
- Leave `review_decision` and `review_notes` empty. This PRD does not implement review state persistence or automatic ingestion.
- Do not generate an HTML contact sheet in this implementation. The current image values are object paths, not guaranteed browser-renderable local image URLs.
- Keep the artifact format simple JSON plus XLSX, reusing existing reporting dependencies.
- The ADR for Focused Feedback Attempts governs the architectural trade-off: clearer attribution over broad single-proposal coverage.

## Testing Decisions

- Tests should verify external behavior and artifact contracts, not private implementation details.
- Group selection tests should cover fixed priority order, exclusion of secondary groups, skipping groups with failed strategy memory, and allowing one follow-up after improvement.
- LLM message tests should verify that only the focused group is active row-level target evidence and inactive groups are background evidence.
- Autorun tests should verify that focused group targets expand to Dev Evaluation Set row targets before Candidate Evaluation Delta comparison.
- Autorun tests should verify that unchanged or regressed focused attempts create Failed Strategy Memory and prevent retrying the same group in the same session.
- Autorun tests should verify that all primary groups can be attempted before no-business-learning stop when none improves.
- Candidate delta tests remain responsible for row-level improvement, regression, persistent failure, strict-only, and infrastructure classification.
- Reporting tests should verify `feedback-failures` examples include `origin` and `card_image`.
- Reporting tests should verify the feedback review workbook headers and one row per feedback failure.
- Existing regression-gate and prompt-gate tests should remain separate.
- Verification should include `uv run pytest -q`.

## Out of Scope

- Cross-session Failed Strategy Memory.
- A global experiment log.
- Automatically mutating the Gift Card Code Evaluation Set, Regression Evaluation Set, or Holdout Evaluation Set.
- Editable review workflow, review import, or review status persistence.
- HTML contact sheet generation or image downloading.
- Changing OCR runtime behavior, image retrieval, provider routing, or model selection.
- Changing Business Code Match or Strict Code Match scoring semantics.
- Optimizing Secondary Code Cleanliness Signal groups while primary Business Code Match failures remain.
- Changing Card Type Recognition Optimization behavior.
- Creating execution CSV tasks.

## Further Notes

- The motivating run was the session that produced valid dev-only row targets but still stopped with no-business-learning: targeted rows stayed unchanged while broader prompt changes introduced regressions.
- The first implementation should stay small: focused scheduling, run-local failed strategy evidence, richer feedback artifacts, and review workbook output.
- If manual review shows primary rows are unreadable or mislabeled, those rows should be handled through dataset or regression-set workflow, not prompt mutation.
