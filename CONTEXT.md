# Card OCR Prompt Optimization

This context names the evaluation goals used when optimizing gift card OCR prompts.

## Language

**Gift Card Code Recognition Optimization**:
An optimization goal focused only on recognizing redeemable gift card code values.
_Avoid_: Card type optimization, metadata optimization

**Gift Card Code Optimization Boundary**:
Gift card code recognition optimization may change code extraction, number output, and code-candidate detection rules across simple, complex, and complete OCR prompts. It must not change physical-versus-electronic type classification, brand, country, currency, or denomination rules.
_Avoid_: Card type optimization boundary, metadata optimization boundary

**Card Type Recognition Optimization**:
An optimization goal focused only on recognizing whether a gift card code belongs to a physical card or an electronic code.
_Avoid_: cardType optimization, country optimization, currency optimization, denomination optimization

**Card Type**:
The physical form classification of a gift card code, either physical card or electronic code.
_Avoid_: Brand, cardType, country, currency, denomination

**Card Type Evaluation Set**:
A manually labeled dataset for card type recognition optimization. Each row contains `card_image`, `origin`, and `golden_type`.
_Avoid_: Gift card code evaluation set, metadata evaluation set

**Gift Card Code Evaluation Set**:
A manually labeled dataset for gift card code recognition optimization. Each row contains `card_image`, `origin`, and `md5_card_number`.
_Avoid_: Card type evaluation set, metadata evaluation set

**Full Evaluation Set**:
The complete routine evaluation set used to report overall optimization quality and acceptance outcomes. It may provide aggregate background evidence for optimizer proposals, but it is not the source of targetable failures during normal optimization.
_Avoid_: Dev evaluation set, optimizer feedback set, holdout evaluation set

**Dev Evaluation Set**:
A manually labeled routine feedback subset for prompt optimization. It is used to compare candidate prompts with the Accepted Prompt on targetable cases during normal optimization.
_Avoid_: Full evaluation set, holdout evaluation set, regression evaluation set

**Optimizer Feedback Set**:
The evaluation set used to choose targetable failures and feedback for automatic optimizer proposals. For Gift Card Code Recognition Optimization, it is the Dev Evaluation Set so target failures can be checked again through Candidate Evaluation Delta.
_Avoid_: Full evaluation set, holdout evaluation set, regression evaluation set

**Human-Reviewed Optimizer Feedback**:
An explicit human-reviewed overlay on the Optimizer Feedback Set. It keeps only failures a reviewer marked as prompt-solvable and may promote a Secondary Code Cleanliness Signal into targetable feedback for a Focused Feedback Attempt.
_Avoid_: automatic dataset mutation, regression evaluation set, unreviewed optimizer feedback

**review_group_key**:
A human-provided structured group key that can refine or replace the original feedback group for prompt-solvable reviewed rows.
_Avoid_: review notes parsing, raw failure category, unstructured group inference

**Feedback Failure Group**:
A group of unresolved Optimizer Feedback Set failures that share the same business error pattern. It describes a rule-level optimization target instead of asking the optimizer to memorize individual rows.
_Avoid_: Full failure cluster, regression candidate, optimizer background evidence

**Focused Feedback Attempt**:
A candidate prompt attempt that targets exactly one primary Feedback Failure Group from the Optimizer Feedback Set. Other groups may remain background evidence, but they are not active row-level targets for that attempt.
_Avoid_: multi-group optimizer proposal, full evaluation target, secondary cleanup attempt

**Failed Strategy Memory**:
Run-local evidence that a specific strategy for a Feedback Failure Group did not improve the targeted rows or caused regressions. It discourages repeating the same strategy, but it is not a global experiment log or a Regression Evaluation Set.
_Avoid_: global experiment log, regression candidate, accepted prompt history

**Optimizer Background Evidence**:
Aggregate evaluation evidence that may help the optimizer understand overall failure shape, but must not be treated as targetable row-level feedback.
_Avoid_: Optimizer feedback set, candidate evaluation delta, regression evaluation set

**Business Code Match**:
A code match focused on redeemability. It allows format differences that do not change whether the redeemable code was found.
_Avoid_: Strict code match, exact text match

**Strict Code Match**:
A code match focused on output cleanliness and strict character presentation. It is useful for detecting formatting differences, extra output, and strict character issues, but it is not the primary acceptance target for Gift Card Code Recognition Optimization.
_Avoid_: Business code match, redeemability match

**Secondary Code Cleanliness Signal**:
A non-primary signal for output cleanliness, including extra code output and strict formatting issues. It should not drive primary optimizer targets while Business Code Match failures remain.
_Avoid_: Business code match, targetable business failure, regression evaluation set

**Security PIN Extra Output**:
A reviewed extra-output pattern where the redeemable gift card code is found, but a separate security PIN is also returned even though the optimization goal only needs the gift card code.
_Avoid_: redeemable code, code plus PIN output, barcode extra output

**Barcode or Receipt Number Extra Output**:
A reviewed extra-output pattern where the redeemable gift card code is found, but a barcode number, receipt number, or transaction number is also returned even though it is not a redeemable gift card code.
_Avoid_: security PIN extra output, redeemable code, serial number target

**Regression Evaluation Set**:
A human-maintained, manually confirmed guard dataset for an optimization goal. It contains cases that should already pass and must not regress when accepting a prompt change. Optimizer runs may read it, but must not automatically add cases to it.
_Avoid_: Candidate set, full evaluation set, automatically promoted regression set

**Regression Candidate**:
A sample automatically suggested during optimization as a possible future regression guard. It is recorded as run evidence and is not part of a Regression Evaluation Set until a human confirms the ground truth and promotes it.
_Avoid_: Regression evaluation set, automatically accepted guard case

**Holdout Evaluation Set**:
A manually labeled evaluation dataset withheld from routine optimization feedback. It is used to detect overfitting after optimizer behavior has already improved on the normal evaluation set.
_Avoid_: Regression evaluation set, full evaluation set, routine dev set

**Accepted Prompt**:
The prompt currently recognized as the baseline by the optimization workflow. A candidate prompt replaces it only after passing the selected task's acceptance conditions.
_Avoid_: rejected candidate prompt, previous attempt, optimizer proposal

**Candidate Evaluation Delta**:
The per-row change in evaluation results when a candidate prompt is compared with the current accepted prompt for the same task and evaluation phase. It is feedback evidence for the next optimizer proposal, not an accept gate or a regression guard.
_Avoid_: Regression evaluation set, regression candidate, global experiment log

**Reviewed Target Resolution**:
A human-reviewed target is resolved when a candidate prompt fixes the reviewed failure pattern without reducing redeemable code recognition. It can justify acceptance in review-guided optimization only when Business Code Match does not regress.
_Avoid_: business accuracy improvement, strict-only cleanup, automatic secondary optimization

**No Business Learning**:
A state where consecutive candidate prompts produce no Business Code Match improvements on the Dev Evaluation Set. It means the current optimizer feedback is not sufficient for continued automatic progress.
_Avoid_: Plateau, convergence, no strict improvement

**Optimization Run Session**:
A single prompt optimization invocation's isolated evidence set for one task. It contains the baseline, candidate evaluations, deltas, and stop outcome for that invocation without merging them into a global experiment log.
_Avoid_: Global experiment log, run iteration, accepted prompt

**golden_type**:
The manually labeled answer for card type recognition. Its value repeats `Physics` or `E-codes` once per card image in the same row; mixed-type rows are outside the current scope.
_Avoid_: type, cardType, denomination

**Card Type Match**:
A card type prediction is correct when the predicted type value equals or contains the manually labeled `golden_type`. For multiple card images in one row, predicted type values are concatenated in image order before matching.
_Avoid_: Code match, brand match, metadata match

**Card Type Optimization Boundary**:
Card type recognition optimization may change only the `type` classification rules for physical card versus electronic code, and those changes apply to both complex and complete OCR prompts. It must not change gift card code extraction, detection, output format, brand, country, currency, denomination, or number rules.
_Avoid_: Code optimization boundary, metadata optimization boundary

## Example Dialogue

Dev: Is this experiment optimizing card type?
Domain expert: Only if it measures physical card versus electronic code. Brand and amount are separate concerns.

Dev: Should a card type optimization change redemption code extraction rules?
Domain expert: No. Code recognition and card type recognition are separate optimization goals.

Dev: Can the optimizer add a promising sample directly to the regression set?
Domain expert: No. It may collect a Regression Candidate, but a human must confirm it before it becomes a Regression Evaluation Set guard.
