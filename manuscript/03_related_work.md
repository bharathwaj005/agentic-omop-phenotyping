<!-- src: manuscript/03_related_work.md -->
# Related Work

### Computable Phenotyping and Common Data Models
Computable phenotyping bridges the semantic divide between raw electronic health record entries and epidemiological research definitions [1, 2]. Standardized vocabularies within the OMOP CDM map disparate institutional coding systems into unified concept identifiers across clinical domains [CITATION NEEDED: OMOP CDM]. While formal phenotype libraries provide peer-reviewed definitions, developing new phenotypes requires extensive manual curation [2, 10].

### Agentic AI in Clinical Research Workflows
The evolution of LLMs from passive sequence predictors into autonomous, goal-directed agentic systems has introduced new paradigms for health data science [2, 9]. Agentic systems leverage external tool invocation, multi-step memory, and deterministic validation guards [9]. Frameworks such as Causal-Copilot [3], TrialGenie [4], EHRFlow [5], and FastOMOP [6] have applied agentic loops to causal inference, clinical trial design, and script generation. 

However, systematic benchmarking by Liu et al. [7] and MedAgentBench [8] showed that agentic systems often exhibit compounding error trajectories. The necessity of multi-agent division of labor versus constrained single-agent prompting remains an open debate [7, 9].

### Comparison with Contemporary Phenotype Extraction Systems
The closest contemporary investigation to our work is that of Chen et al. (2026) [10], who evaluated agentic authoring of OMOP concept sets. Our investigation differs in four fundamental dimensions:
- **Scope of Generation:** Chen et al. focused on isolated concept sets. We synthesize full, executable cohort specifications comprising temporal index events, entry windows, demographic bounds, and exclusion logic.
- **Architectural Ablation:** We isolate multi-agent planning, iterative critique, and schema validation against a single-agent baseline under identical compute budgets.
- **Hardware Profile:** While Chen et al. leveraged hosted commercial cloud endpoints, our pipeline executes locally on consumer-grade hardware (Intel Core i3, 8 GB RAM).
- **Reference Topology:** We introduce multi-arm reference corrections to account for disjunctive entry criteria within the OHDSI Phenotype Library.
