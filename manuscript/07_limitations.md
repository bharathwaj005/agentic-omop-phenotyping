# 6. Limitations

1. **Concept-level evaluation:** Fidelity was assessed at the concept-set level against Reference v2, the standard for vocabulary fidelity; patient-level agreement of the generated cohorts is the natural next step.
2. **Model and run scale:** Experiments used a single quantized 7B model (`qwen2.5:7b`), matching the 8 GB RAM hardware target, with one deterministic pass per task and configuration. The open release allows replication with other models and repeated runs.
3. **Multiplicity and design:** Neurological and ADN comparisons were significant before but not after Holm–Bonferroni adjustment (p = 0.094); the ADN track and the hierarchy-aware analysis were designed after the primary results, although the ADN track was frozen before its runs. V5.3 paired tests are restricted to tasks scored by both configurations, so intention-to-evaluate means are reported alongside.
4. **Benchmark composition:** System development used task T01 only. Some tasks share a target condition (T01, T06 and T10: ADHD; N06 and N07: acute disseminated encephalomyelitis; T08, N01 and A01: Alzheimer's disease under different definitions), and one reference (T10) was corrected after the runs by re-scoring stored outputs (Section 3).

---
