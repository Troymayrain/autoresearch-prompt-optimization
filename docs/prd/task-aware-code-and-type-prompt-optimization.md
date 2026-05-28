# PRD: Task-Aware Gift Card Code And Card Type Prompt Optimization

## Problem Statement

The current optimizer has one optimization flow focused on gift card code recognition. It asks the optimizer LLM to rewrite the whole OCR prompt file and accepts any prompt that improves code accuracy. This allowed an accepted prompt change to modify card type classification rules even though the business goal was only to improve redeemable code recognition.

The project now needs two clearly separated optimization goals: Gift Card Code Recognition Optimization and Card Type Recognition Optimization. Each goal needs its own commands, dataset schema, scoring semantics, optimizer instructions, prompt mutation boundary, and gate enforcement so that one optimization task cannot accidentally change the other task's rules.

## Solution

Add task-aware optimization to the existing prompt optimizer. A single optimizer entrypoint will accept a task value and run the shared dev/full/plateau keep-discard loop with task-specific dataset loading, scoring, reporting, optimizer context, and prompt boundary gate.

The four user-facing commands will be:

1. `uv run poe code-smoke`
2. `uv run poe code-full`
3. `uv run poe type-smoke`
4. `uv run poe type-full`

Gift Card Code Recognition Optimization will continue to use the existing code evaluation datasets and `md5_card_number` golden answer. Card Type Recognition Optimization will use datasets containing `card_image`, `origin`, and `golden_type`, where `golden_type` repeats `Physics` or `E-codes` once per card image in the row.

The optimizer LLM may still propose a full prompt file, but the prompt gate will reject task-boundary violations. Code optimization may change code extraction, number output, and code-candidate detection rules, but not type or metadata rules. Type optimization may change only the physical-versus-electronic `type` classification rules in the complex and complete OCR prompts, and must not change code extraction, detection, output format, brand, country, currency, denomination, or number rules.

## User Stories

1. As a prompt optimizer user, I want separate commands for code and type optimization, so that I do not accidentally run the wrong experiment.
2. As a prompt optimizer user, I want `code-smoke` to run a small Gift Card Code Recognition Optimization dataset, so that I can verify the code path quickly.
3. As a prompt optimizer user, I want `code-full` to run the full Gift Card Code Recognition Optimization dataset, so that I can optimize redeemable code accuracy.
4. As a prompt optimizer user, I want `type-smoke` to run a small Card Type Recognition Optimization dataset, so that I can verify card type scoring quickly.
5. As a prompt optimizer user, I want `type-full` to run the full Card Type Recognition Optimization dataset, so that I can optimize physical-versus-electronic classification.
6. As a prompt optimizer user, I want code optimization to read datasets with `card_image`, `origin`, and `md5_card_number`, so that existing code recognition datasets keep working.
7. As a prompt optimizer user, I want type optimization to read datasets with `card_image`, `origin`, and `golden_type`, so that card type datasets have a clear contract.
8. As a prompt optimizer user, I want `golden_type` to support repeated values such as `PhysicsPhysics` or `E-codesE-codes`, so that one row can represent multiple card images.
9. As a prompt optimizer user, I want multiple card images in one row to keep their image order, so that predicted types can be compared against the repeated `golden_type` value.
10. As a prompt optimizer user, I want the type scorer to concatenate predicted `type` values in image order, so that multi-image rows can be scored consistently.
11. As a prompt optimizer user, I want a predicted type to be correct when it equals or contains `golden_type`, so that the scoring rule matches the current labeled dataset convention.
12. As a prompt optimizer user, I want rows without evaluable type output to be reported separately, so that card type optimization is not forced to fix code detection or code extraction.
13. As a prompt optimizer user, I want code optimization to ignore `type`, `cardType`, `country`, `currency`, and `denomination` fields in scoring, so that code accuracy remains the only code-task target.
14. As a prompt optimizer user, I want type optimization to ignore `cardType`, `country`, `currency`, `denomination`, and code-number correctness in scoring, so that physical-versus-electronic classification remains the only type-task target.
15. As a prompt optimizer user, I want code optimization to be allowed to adjust code-candidate detection, so that `no-card` failures can be reduced.
16. As a prompt optimizer user, I want code optimization to be forbidden from changing type classification rules, so that code experiments cannot damage type behavior.
17. As a prompt optimizer user, I want type optimization to be forbidden from changing code detection rules, so that type experiments cannot change whether OCR runs.
18. As a prompt optimizer user, I want type optimization to be forbidden from changing code extraction and number output rules, so that type experiments cannot mask classification improvements with code-recognition changes.
19. As a prompt optimizer user, I want type optimization to update complex and complete type rules together, so that evaluated behavior and complete-output behavior do not drift apart.
20. As a prompt optimizer user, I want the prompt gate to reject a code-task proposal that changes type or metadata sections, so that task boundaries are enforced automatically.
21. As a prompt optimizer user, I want the prompt gate to reject a type-task proposal that changes code, detection, output format, or metadata sections, so that task boundaries are enforced automatically.
22. As a prompt optimizer user, I want optimizer prompts to explain the task boundary to the LLM, so that fewer proposals are rejected by the gate.
23. As a prompt optimizer user, I want rejected boundary-violation proposals to be recorded with an explicit gate error, so that I can understand why a run did not evaluate.
24. As a prompt optimizer user, I want dev/full/plateau behavior to stay consistent across code and type tasks, so that both tasks use the same keep-discard policy.
25. As a prompt optimizer user, I want run artifacts to show which task produced them, so that code and type experiment outputs are not confused.
26. As a prompt optimizer user, I want summaries to expose task-specific accuracy and failure categories, so that I can compare runs without opening the raw result workbook.
27. As a prompt optimizer user, I want accepted prompt commits to include the task name and accuracy, so that git history shows whether a prompt was accepted for code or type optimization.
28. As a prompt optimizer maintainer, I want the scoring modules to be isolated and testable, so that new task metrics do not destabilize the optimizer loop.
29. As a prompt optimizer maintainer, I want the prompt boundary gate to be isolated and testable, so that prompt safety rules are not buried inside the autorun loop.
30. As a prompt optimizer maintainer, I want task-specific dataset parsing to be explicit, so that a mislabeled Excel file fails early with a clear message.

## Implementation Decisions

- Use one shared optimizer entrypoint with a required task value: `code` for Gift Card Code Recognition Optimization and `type` for Card Type Recognition Optimization.
- Keep one shared optimization loop for baseline evaluation, LLM proposal, gate validation, dev evaluation, full evaluation, keep/discard, plateau, and commit behavior.
- Add four Poe tasks: `code-smoke`, `code-full`, `type-smoke`, and `type-full`.
- Use the existing code datasets for code commands: one smoke dataset and one full dataset.
- Use new default type datasets named for type OCR smoke and full evaluation.
- A Gift Card Code Evaluation Set contains `card_image`, `origin`, and `md5_card_number`.
- A Card Type Evaluation Set contains `card_image`, `origin`, and `golden_type`.
- `golden_type` repeats one canonical type value per card image in the same row. The supported type values are `Physics` and `E-codes`.
- Mixed-type multi-image rows are out of scope for the first implementation.
- Multi-image rows continue to represent images with `||` in `card_image`. The OCR runtime already splits this input; the Python task layer should preserve row-level evaluation.
- For type scoring, predicted OCR response items are read in order, their `type` values are concatenated, and the result is compared against `golden_type`.
- For type scoring, a prediction is correct when the concatenated predicted type value equals or contains `golden_type`; otherwise it is wrong.
- For type scoring, missing OCR objects, missing `type`, or OCR infrastructure failures are reported as not evaluable rather than as type mistakes.
- The type accuracy denominator contains only evaluable type predictions.
- Type summary output should also show not-evaluable counts so users can detect when type accuracy is being computed on too little usable output.
- Code scoring remains based on redeemable code `number` values and the existing business matching semantics.
- Code optimization may change code extraction rules, number output rules, and code-candidate detection rules.
- Code optimization must not change physical-versus-electronic type classification, brand, country, currency, or denomination rules.
- Type optimization may change only physical-versus-electronic `type` classification rules.
- Type optimization may change type rules in both complex and complete OCR prompts, and those rules should stay aligned.
- Type optimization must not change code extraction, code-candidate detection, output format, brand, country, currency, denomination, or number rules.
- The optimizer LLM system message should be task-aware and describe the allowed mutation boundary for the selected task.
- The prompt gate should remain responsible for JavaScript syntax, required exports, static prompt-file validation, and task-boundary enforcement.
- The prompt boundary gate should compare the accepted prompt and proposed prompt structurally enough to identify whether protected prompt sections changed.
- Gate failure should not run OCR evaluation for that proposal.
- First gate failure retry behavior should remain: restore the accepted prompt, give the LLM the gate error, and retry once.
- Reporting should include the task name in summaries and optimizer request context.
- Failure clusters should be task-specific: code tasks keep code-recognition categories; type tasks add type mismatch and not-evaluable categories.
- Accepted commits should make the optimized task visible in the commit message.

## Testing Decisions

- Tests should focus on external behavior: command contracts, dataset schema acceptance/rejection, scoring outputs, gate acceptance/rejection, reporting summaries, and autorun keep/discard behavior.
- Dataset tests should verify that code datasets require `md5_card_number` and type datasets require `golden_type`.
- Dataset tests should verify clear failures for missing required columns and invalid `golden_type` values.
- Type scoring tests should cover single-image correct, single-image incorrect, multi-image repeated `Physics`, multi-image repeated `E-codes`, contains-matching, and missing-type not-evaluable cases.
- Code scoring tests should remain focused on current business matching semantics and should not be changed to include type behavior.
- Evaluation tests should verify that code tasks extract actual numbers and type tasks extract actual types without changing OCR runtime behavior.
- Prompt gate tests should cover code-task allowed changes, code-task forbidden type changes, code-task forbidden metadata changes, type-task allowed type-rule changes, type-task forbidden detect changes, type-task forbidden number/output changes, and type-task forbidden metadata changes.
- LLM message tests should verify that the selected task appears in the optimizer instructions and that the task boundary is explicit.
- Autorun tests should verify that code and type tasks both use dev/full/plateau keep-discard behavior.
- Autorun tests should verify that gate-failed proposals record artifacts and do not evaluate OCR.
- Reporting tests should verify that summaries include the task name and task-specific accuracy fields.
- Poe command tests can be lightweight manifest checks that assert all four command names exist and point to the expected task and dataset.
- Prior art exists in the current config, dataset, scoring, evaluation, prompt gate, LLM, reporting, and autorun tests; new tests should extend those patterns instead of introducing a new test framework.

## Out of Scope

- Optimizing `cardType`.
- Optimizing `country`.
- Optimizing `currency`.
- Optimizing `denomination`.
- Supporting mixed-type multi-image rows such as one physical card and one electronic code in the same row.
- Changing the OCR runtime request mode or provider routing.
- Changing image download, decrypt, S3, AI gateway, or local image loading behavior.
- Changing the keep/discard algorithm beyond adding task-aware scoring and gate rules.
- Adding a UI.
- Creating or modifying production deployment infrastructure.
- Making the optimizer edit files other than the prompt file.

## Further Notes

- The distinction between Gift Card Code Recognition Optimization and Card Type Recognition Optimization is now part of the project glossary.
- Card Type means only physical card versus electronic code. It does not mean brand or metadata.
- The prompt gate is the main safety mechanism. LLM instructions reduce bad proposals, but gate enforcement is the source of truth.
- Type optimization intentionally does not try to fix code extraction failures. If too many rows are not evaluable, that is a dataset/runtime signal, not a reason for the type optimizer to change code rules.
- This PRD could not be published to GitHub Issues from the current machine because the `gh` CLI is not installed. It is ready to publish with the `ready-for-agent` label once `gh` is available.
