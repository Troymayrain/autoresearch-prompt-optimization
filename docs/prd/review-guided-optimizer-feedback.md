# PRD: Review-Guided Optimizer Feedback

## Problem Statement

Gift Card Code Recognition Optimization can now produce a review workbook, but the optimizer cannot consume the reviewer's conclusions. After manual review, users can identify rows that are label errors, unreadable images, already-correct model behavior, or prompt-solvable extra output, yet `code-full` still treats the unreviewed Dev Evaluation Set as the only target source.

This blocks useful optimization after data cleanup. In the current reviewed run, most former primary failures were removed by dataset correction, while five `extra_code_output` rows were manually confirmed as prompt-solvable. The automatic optimizer still treats extra output as a Secondary Code Cleanliness Signal and does not promote those reviewed rows into Focused Feedback Attempts.

## Solution

Add Review-Guided Optimizer Feedback. When a user explicitly passes a review workbook, the optimizer builds a Human-Reviewed Optimizer Feedback overlay from rows marked `prompt_fixable`. The overlay may promote reviewed secondary rows into active focused groups, while excluded rows remain audit evidence and unreviewed rows may stay background-only.

The review workflow uses a structured `review_group_key` column rather than parsing review notes. For the current extra-output case, reviewers can split `extra_code_output` into `extra_code_security_pin` and `extra_code_barcode_receipt_number`, allowing the optimizer to attempt one narrow group at a time.

Review-guided acceptance uses Reviewed Target Resolution. A candidate can be accepted when it resolves at least one reviewed target and does not regress Dev or Full Business Code Match or Strict Code Match. Regression gate behavior remains unchanged when configured.

## User Stories

1. As a prompt optimizer user, I want to pass a review workbook explicitly, so that manual triage can guide the next optimization run.
2. As a prompt optimizer user, I want default `code-full` behavior to remain unchanged unless I pass a review workbook, so that existing automation is not surprised by review artifacts.
3. As a prompt optimizer user, I want only `prompt_fixable` review rows to become active targets, so that label errors and unreadable images do not drive prompt mutation.
4. As a prompt optimizer user, I want `label_wrong`, `image_unreadable`, and empty review rows excluded from active targets, so that optimizer proposals focus only on human-confirmed prompt-solvable failures.
5. As a prompt optimizer user, I want unreviewed rows to remain background-only evidence, so that the optimizer can avoid collateral damage without targeting unconfirmed failures.
6. As a prompt optimizer user, I want `review_group_key` to refine a failure group, so that reviewed rows can be split into precise prompt-solvable patterns.
7. As a prompt optimizer user, I want review notes to remain audit text only, so that machine behavior does not depend on natural-language note parsing.
8. As a prompt optimizer user, I want `extra_code_security_pin` rows grouped together, so that the prompt can learn that a gift card security PIN should not be output when the redeemable code is present.
9. As a prompt optimizer user, I want `extra_code_barcode_receipt_number` rows grouped together, so that the prompt can learn to ignore barcode numbers, receipt numbers, and transaction numbers.
10. As a prompt optimizer user, I want reviewed extra-output groups to become Focused Feedback Attempts, so that Secondary Code Cleanliness Signal rows can be optimized after human confirmation.
11. As a prompt optimizer user, I want a review-guided run to write `review-feedback.json`, so that I can audit which reviewed rows were active, excluded, already resolved, or mismatched.
12. As a prompt optimizer user, I want the raw `feedback-failures.json` preserved, so that I can compare automatic evaluation failures with human-reviewed optimizer feedback.
13. As a prompt optimizer user, I want rows already resolved in the current Dev Evaluation Set to be recorded rather than re-optimized, so that stale review workbooks do not force useless attempts.
14. As a prompt optimizer user, I want mismatched reviewed rows excluded from active targets, so that stale or contradictory review evidence does not mutate the prompt.
15. As a prompt optimizer user, I want `dev-delta.json` to show `reviewed_target_effect`, so that extra-output improvements are visible even when Business Code Match is unchanged.
16. As a prompt optimizer user, I want a reviewed target to count as resolved only when the expected redeemable code remains present and the reviewed extra output is removed, so that cleanup does not hide code recognition regressions.
17. As a prompt optimizer user, I want review-guided acceptance to require no Dev Business Code Match regression, so that output cleanup cannot reduce redeemable code recognition.
18. As a prompt optimizer user, I want review-guided acceptance to require no Dev Strict Code Match regression, so that a local cleanup does not make other outputs dirtier.
19. As a prompt optimizer user, I want review-guided acceptance to require no Full Business Code Match regression, so that accepted prompts remain safe on the full routine evaluation set.
20. As a prompt optimizer user, I want review-guided acceptance to require no Full Strict Code Match regression, so that accepted prompts do not trade one clean row for broader formatting damage.
21. As a prompt optimizer user, I want regression gates to remain enforced when configured, so that review-guided improvements do not bypass existing guards.
22. As a prompt optimizer user, I want review-guided exhaustion to stop with `review_feedback_exhausted`, so that extra-output stagnation is not mislabeled as no business learning.
23. As a prompt optimizer user, I want a workbook migration helper, so that old review workbooks can gain `review_group_key` without relying on manual column edits.
24. As a prompt optimizer user, I want the migration helper to set groups by row number only, so that it never guesses from free-form notes.
25. As a prompt optimizer maintainer, I want review import isolated behind a small module, so that workbook parsing, validation, filtering, and grouping can be tested without running OCR.
26. As a prompt optimizer maintainer, I want reviewed target resolution isolated from regular Candidate Evaluation Delta semantics, so that Business Code Match remains the primary automatic optimization metric.
27. As a prompt optimizer maintainer, I want CLI validation to reject review workbooks for type tasks, so that code-only review semantics do not leak into Card Type Recognition Optimization.
28. As a reviewer, I want tests proving `review_group_key` is required for split extra-output rows, so that future changes do not reintroduce natural-language note parsing.
29. As a reviewer, I want tests proving unreviewed or non-prompt-fixable rows cannot become active targets, so that review-guided mode remains conservative.
30. As a reviewer, I want tests proving legacy runs still behave the same without `--review-workbook`, so that review-guided optimization does not regress automatic Dev-only focused feedback.

## Implementation Decisions

- Add a review-guided mode behind an explicit optional `--review-workbook` CLI argument.
- Keep the existing automatic Dev-only focused feedback behavior unchanged when no review workbook is passed.
- Restrict review-guided mode to Gift Card Code Recognition Optimization.
- Add `review_group_key` to newly generated feedback review workbooks.
- Treat `review_decision=prompt_fixable` as the only review decision that can become active optimizer feedback.
- Treat `label_wrong`, `image_unreadable`, empty review decisions, and unknown review decisions as excluded from active optimizer targets.
- Require `review_group_key` for reviewed `extra_code_output` rows that need split grouping.
- Use `review_group_key` as machine-readable grouping and keep `review_notes` as human audit text.
- Build a Human-Reviewed Optimizer Feedback overlay that preserves raw feedback evidence separately from reviewed active feedback.
- Write `review-feedback.json` alongside the baseline artifacts without overwriting `feedback-failures.json`.
- Record active groups, background groups, excluded rows, already-resolved rows, mismatched rows, and the source review workbook in `review-feedback.json`.
- Promote reviewed Secondary Code Cleanliness Signal rows into targetable Focused Feedback Attempts only inside review-guided mode.
- Use review-guided priority order: reviewed primary business groups, `extra_code_security_pin`, `extra_code_barcode_receipt_number`, other reviewed `extra_code_output`, then other reviewed groups.
- Add `reviewed_target_effect` to candidate delta artifacts in review-guided mode.
- Keep the existing `target_failures_effect` business/type semantics unchanged.
- Accept review-guided candidates only when at least one reviewed target resolves and Dev/Full Business Code Match and Strict Code Match do not regress.
- Preserve existing regression gate behavior after review-guided Dev and Full gates.
- Stop exhausted review-guided runs with `review_feedback_exhausted`.
- Add a migration helper that can copy an existing review workbook and explicitly set `review_group_key` by row number.
- Do not mutate the Gift Card Code Evaluation Set, Regression Evaluation Set, or Holdout Evaluation Set from review-guided feedback.

## Testing Decisions

- Tests should verify external behavior and artifact contracts, not private implementation details.
- Review feedback import tests should cover required workbook columns, prompt-fixable filtering, excluded row categories, unknown row handling, already-resolved rows, mismatched rows, and `review_group_key` validation.
- Review feedback scheduler tests should cover promotion of reviewed secondary rows and review-guided priority order.
- Reporting tests should verify new feedback review workbooks include `review_group_key`.
- Candidate delta tests should verify `reviewed_target_effect` reports resolved, unchanged, regressed, ignored, and summary counts without changing `target_failures_effect`.
- Autorun tests should verify `--review-workbook` is accepted for code, rejected for type, and preserves legacy behavior when omitted.
- Autorun tests should verify a reviewed extra-code target can be accepted when Business Code Match is unchanged but reviewed target resolution succeeds and strict metrics do not regress.
- Autorun tests should verify review-guided candidates are rejected when Dev or Full Business Code Match or Strict Code Match regresses.
- Migration helper tests should verify explicit row-number group assignment and no natural-language note parsing.
- Verification should include targeted tests during implementation and `uv run pytest -q` before closure.

## Out of Scope

- Automatically mutating source evaluation datasets from review workbooks.
- Automatically adding reviewed rows to Regression Evaluation Sets or Holdout Evaluation Sets.
- Parsing `review_notes` to infer groups or decisions.
- Supporting review-guided mode for Card Type Recognition Optimization.
- Changing OCR runtime behavior, image retrieval, provider routing, or model selection.
- Changing Business Code Match normalization or Strict Code Match normalization.
- Building a UI for review editing.
- Running live OCR as part of unit tests.
- Creating a global cross-session experiment log.

## Further Notes

- This PRD follows ADR 0005. Review-guided optimization intentionally overrides the default secondary-target exclusion only when a review workbook is explicitly supplied.
- The current motivating review confirmed five prompt-solvable extra-output rows: `113`, `258`, and `316` for Security PIN Extra Output; `91` and `31` for Barcode or Receipt Number Extra Output.
- The implementation should keep review import and reviewed target resolution as deep, testable modules with small public interfaces.
