# Candidate Evaluation Delta Feedback Loop

Prompt optimization will feed Candidate Evaluation Delta evidence from rejected dev runs back into the next optimizer request, while keeping acceptance based on the current Accepted Prompt and the existing dev, full, and regression gates. This gives the optimizer concrete row-level evidence about task-specific improvements, regressions, persistent failures, secondary metric changes, and infrastructure failures without turning rejected candidates into a new baseline or adding a global experiment log.

**Consequences**

- Candidate Evaluation Delta is run-local feedback evidence, not a Regression Evaluation Set, Regression Candidate, or holdout mechanism.
- Business Code Match remains the primary signal for Gift Card Code Recognition Optimization; Strict Code Match is secondary feedback unless a strict optimization mode is explicitly introduced.
- Rejected candidates may inform later proposals, but they must not move the Accepted Prompt baseline or regression baseline.
- Runs may stop early when repeated dev-evaluated candidates show no business learning; this reports optimizer stagnation without accepting a worse candidate or changing guard datasets.
- Each optimizer invocation should write to an isolated Optimization Run Session so stale candidate artifacts from a previous invocation cannot be mistaken for current evidence; this is still run-local evidence, not a global experiment log.
