<!-- src: manuscript/07_limitations.md -->
# Limitations

1. **Synthetic Patient Population:** Patient-level execution was evaluated against synthetic OMOP Eunomia data (2,694 patients), which lacks the full noise and missingness of real-world EHR repositories.
2. **Patient Overlap in Neurological Track:** Within Eunomia, Alzheimer's disease and broader dementia definitions shared an identical sub-cohort of 136 patients. Consequently, 10 of 12 Neurological tasks were scored at concept level only.
3. **Single Local Model Scale:** Experiments were conducted using a single quantized 7B model (`qwen2.5:7b`) due to the 8 GB RAM consumer hardware budget.
4. **Single Run Allocation:** Primary benchmark tasks were executed as single deterministic passes under fixed seeds rather than multi-run stochastic distributions.
5. **Development Set Contamination:** System development utilized task T01. The remaining 19 tasks in V5.3 and all 12 tasks in Neuro were evaluated without task-specific optimization.
