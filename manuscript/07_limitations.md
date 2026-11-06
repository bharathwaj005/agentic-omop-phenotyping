# 6. Limitations

1. **Concept-level evaluation only:** Fidelity was assessed at the concept-set level against Reference v2. Patient-level agreement of the generated cohorts was not evaluated and remains future work.
2. **Single Local Model Scale:** Experiments were conducted using a single quantized 7B model (`qwen2.5:7b`) due to the 8 GB RAM consumer hardware budget.
3. **Single Run Allocation:** Primary benchmark tasks were executed as single deterministic passes under fixed seeds rather than multi-run stochastic distributions.
4. **Development Set Contamination:** System development utilized task T01. The remaining 19 tasks in V5.3 and all 12 tasks in Neuro were evaluated without task-specific optimization.
5. **Conditional paired comparisons (V5.3):** Paired tests are restricted to tasks scored by both configurations (10–11 of 20 in V5.3), a subset defined partly by C1 success; the comparisons therefore favour C1, and intention-to-evaluate means (All = 0) are reported alongside.
6. **Benchmark redundancy and reference error:** Three V5.3 tasks (T01, T06 and T10) target ADHD under different definitions, so the effective diversity of the general track is lower than its task count. One reference (T10) was built from the wrong cohort and was corrected after the runs (Section 3); other reference errors of this kind cannot be fully excluded.
