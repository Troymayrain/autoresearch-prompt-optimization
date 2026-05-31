# Review-Guided Optimizer Feedback

Prompt optimization may use an explicit human review workbook as a Human-Reviewed Optimizer Feedback overlay. When enabled, only rows marked prompt-solvable are active optimizer targets, a structured `review_group_key` may refine the failure group, and reviewed Secondary Code Cleanliness Signal rows may become Focused Feedback Attempts; this trades fully automatic prioritization for reviewer-confirmed prompt-solvable targets.

**Consequences**

- The original `feedback-failures.json` remains raw evaluation evidence; review-guided runs write a separate `review-feedback.json`.
- Review notes are human audit text only. Machine grouping uses `review_group_key` rather than parsing natural language.
- Review-guided acceptance may rely on Reviewed Target Resolution instead of Business Code Match improvement, but dev and full Business Code Match and Strict Code Match must not regress.
- Review-guided feedback must not mutate the Gift Card Code Evaluation Set, Regression Evaluation Set, or Holdout Evaluation Set.
- Without an explicit review workbook, automatic optimization keeps the existing Dev-only focused feedback behavior.
