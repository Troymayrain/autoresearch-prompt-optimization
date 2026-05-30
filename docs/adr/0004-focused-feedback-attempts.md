# Focused Feedback Attempts

Prompt optimization will make one Feedback Failure Group active per optimizer proposal instead of targeting all primary failure groups at once. This trades broad coverage for clearer Candidate Evaluation Delta evidence: when an attempt improves, stays unchanged, or regresses, the workflow can attribute that outcome to a focused strategy rather than to a mixed set of unrelated prompt changes.

**Consequences**

- Other Feedback Failure Groups may remain background evidence, but they are not active row-level targets for the attempt.
- Failed strategies are remembered only within the current Optimization Run Session so the optimizer does not repeat the same unhelpful prompt change during that run.
- Secondary Code Cleanliness Signal groups remain out of automatic primary optimization while Business Code Match failures remain.
