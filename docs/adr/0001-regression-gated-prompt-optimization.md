# Regression-Gated Prompt Optimization

Prompt optimization accepts changes only when they improve the selected task without degrading a human-maintained Regression Evaluation Set. The optimizer may read an explicit `--regression-dataset` and record Regression Candidates as evidence, but it must not automatically add cases to the Regression Evaluation Set; holdout evaluation remains a later overfitting check, not part of the first regression-gate implementation.

**Consequences**

- Regression failure is an accept-gate failure, not a stop condition.
- The accepted regression baseline follows the current accepted prompt rather than staying fixed to the initial prompt.
- Regression datasets reuse the task's existing evaluation schema instead of introducing a separate case database.
- The first implementation does not add holdout gating or a global `experiments.jsonl`.
