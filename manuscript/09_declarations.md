# Declarations

### Data and Code Availability
All experimental pipelines, prompts, schema validators, task definitions, and evaluation scripts are open-source and version-controlled. The complete benchmark suite, blinded clinical questions (`tasks/benchmark_questions.jsonl`, `tasks/adn/`), frozen manifests (`results/codex_20261025/freeze_manifest_OFFICIAL.json`, `results/codex_20261025/freeze_manifest_ADN.json`), run logs, robustness re-runs and secondary analyses (`docs/SENSITIVITY_ANALYSES.md`, `docs/AD_NEUROINFLAMMATION_TRACK.md`) are available at: https://github.com/bharathwaj005/agentic-omop-phenotyping. The OMOP vocabulary tables are accessible via OHDSI Athena (https://athena.ohdsi.org). Pipeline execution checks use the public synthetic OMOP Eunomia dataset.

### Funding
This research received no specific grant from any funding agency in the public, commercial, or not-for-profit sectors.

### Competing Interests
The author declares that he has no known competing financial interests or personal relationships that could have appeared to influence the work reported in this paper.

### Author Contributions
Bharathwaj: Conceptualization, Methodology, Software, Formal analysis, Investigation, Data Curation, Writing - Original Draft, Writing - Review & Editing, Visualization.

### Ethics Statement
This study used only public vocabulary resources and synthetic data; no human participants or identifiable patient data were involved, so ethical approval was not required.

### Declaration of generative AI and AI-assisted technologies in the writing process
During the preparation of this work the author(s) used Claude, Gemini and OpenAI Codex in order to assist with code development, debugging, analysis scripts and drafting text. After using these tools, the author(s) reviewed and edited the content as needed and take(s) full responsibility for the content of the publication.

---

# Appendix A. Supplementary Data

| Task | OHDSI cohort | Phenotype | Role | Ref. size | C1 | C2 | C3 | C4 |
| :--- | :---: | :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| A01 | 100 | Alzheimer's disease | Outcome | 35 | 1.00 | 0.06 | 0.06 | 0.06 |
| A02 | 651 | Dementia | Outcome | 216 | 0.28 | 1.00 | 0.28 | 0.28 |
| A03 | 95 | Delirium | Acute brain dysfunction | 60 | 0.96 | 0.96 | 0.03 | 0.03 |
| A04 | 457 | Rheumatoid arthritis | Chronic inflammation | 134 | 1.00 | 0.01 | 0.01 | 0.01 |
| A05 | 1070 | JAK inhibitor new users (RA) | Treatment | 252 | 0.70 | 0.69 | 0.70 | 0.70 |
| A06 | 1069 | TNFα inhibitor new users (Crohn's) | Treatment | 508 | 0.00 | 0.16 | 0.00 | 0.01 |
| A07 | 629 | Inflammatory bowel disease | Chronic inflammation | 80 | 1.00 | 0.93 | 1.00 | 1.00 |
| A08 | 475 | Psoriasis | Chronic inflammation | 80 | 1.00 | — (1.00) | 1.00 | 1.00 |
| A09 | 509 | Systemic lupus erythematosus | Autoimmune exposure | 33 | 1.00 | 0.00 | 0.06 | 0.06 |
| A10 | 463 | Sepsis | Acute inflammation | 155 | 1.00 | 0.01 | 1.00 | 1.00 |
| A11 | 615 | Herpes simplex | Infection | 156 | 0.25 | 0.01 | 0.01 | 0.01 |
| A12 | 699 | Major depressive disorder | Neuropsychiatric comorbidity | 72 | 1.00 | 0.03 | 0.03 | 0.03 |

*Table A1: Alzheimer's disease neuroinflammation extension track: tasks, OHDSI Phenotype Library cohorts, reference concept-set sizes and exact F1 per configuration. — = non-scored run (inference server terminated for lack of memory); the value in parentheses is the robustness re-run.*

---
