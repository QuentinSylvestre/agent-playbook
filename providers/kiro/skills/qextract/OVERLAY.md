## Scoring formalism (kiro)

The explicit rank scale and arithmetic for `### Step 5: Synthesis phase` § Score. Use this when the prose default there is not enough to decide a tier.

**Precondition — never score before the coverage check.** This arithmetic applies only to concepts that check labelled `absent` or `partial`. A `covered` concept is dropped and never reaches the matrix. Scoring one anyway lands it in Recommended: a restatement of an existing rule reads as Value Medium (2) at Effort Low (1), composite 1, which clears both the Recommended tier and the Apply-directly threshold. The matrix cannot catch a restatement — only the coverage check can.

For a `partial` concept, rank the **delta** it adds, not the whole concept: Effort is the incremental bullets, and Value is what the delta buys over the existing rule.

Score each concept on the 2x2 matrix:

| Dimension | High (3) | Medium (2) | Low (1) |
|---|---|---|---|
| **Value** | Fundamentally improves agent behavior or fills a gap | Useful refinement of existing behavior | Marginal or niche improvement |
| **Effort** | New skill or architectural change | New section or significant rewrite | Add/edit a few bullets |

Note: Effort is inverted for the composite — Low effort = good.

**Composite** = Value rank − Effort rank. Range: −2 to +2.

**Integration tag**:
- "Apply directly" — composite ≥ 1 AND effort = Low (a few bullets to add/edit)
- "Needs `/qplan`" — everything else

**Tier split**:
- **Recommended** — composite ≥ 1 (high value OR low effort)
- **For awareness** — composite < 1

## Thoroughness reminder (kiro)

When dispatching the Step 4 sub-agents, instruct them to extract ALL concepts, even minor ones, and not to self-censor based on perceived value — the orchestrator is the coverage-and-scoring gate, not the extractor. The kiro model tends to prune too early at extraction time; counter that bias here. Extracting broadly is safe precisely because the orchestrator's coverage check drops what the playbook already covers — do not let breadth here become breadth in the report.
