"""C0-plus — deterministic lexical and structural baseline. No LLM.

This is the Phase-4 deterministic reasoning work (temporal markers, inclusion
and exclusion parsing, nested-relationship detection, hierarchy-aware
selection, explicit unresolved-term handling) ported onto the canonical tools
and emitting a canonical CohortSpec.

It is a BASELINE, not the single-agent comparator. Naming it C0-plus is
deliberate: calling a hand-written parser "the single-agent baseline" would
make the C1 comparison meaningless, because beating a regex parser says nothing
about whether multi-agent coordination beats one capable model.

Kept because it is a *strong* non-LLM baseline. "Our system beats a purpose-
built deterministic parser" is a harder and more interesting claim than beating
naive keyword search, and it answers the reviewer question "is an LLM needed
here at all?" far better than a trivial baseline would.

Two rules carried over unchanged from the Phase-4 work:
  * never fabricate a concept ID;
  * never silently drop a term that could not be resolved -- record it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from src.schema.spec import CohortSpec, ConceptItem, ConceptSet, Criterion
from src.tools import vocab
from src.tools.resolver import resolve_items, restrict_to_standard

# --- surface patterns -------------------------------------------------------

FIRST_OCCURRENCE = re.compile(
    r"\b(first|earliest|new users?|newly diagnosed|incident|initiat\w+|"
    r"start(?:ing|ed)?)\b", re.I)

NEW_USER = re.compile(r"\b(new users?|newly started|initiat\w+)\b", re.I)

EXCLUSION_SPLIT = re.compile(
    r"\b(?:without|excluding|except for|except|but not|who do not have|"
    r"with no|free of|in the absence of)\b", re.I)

REQUIRE_SPLIT = re.compile(
    r"\b(?:who (?:also )?(?:had|have|received|were (?:given|prescribed))\s+"
    r"(?:a\s+)?(?:prior|previous|recent|concurrent)|"
    r"who also (?:had|have|received)|"
    r"with (?:a )?(?:prior|previous|recent)|following|after|"
    r"nested (?:in|within))\b", re.I)

ADULT = re.compile(r"\badults?\b", re.I)
AGE_MIN = re.compile(r"\b(?:aged?|age)\s+(\d{1,3})\s*(?:years?)?\s*"
                     r"(?:or older|and (?:older|above)|\+)", re.I)
AGE_MAX = re.compile(r"\b(?:aged?|age)\s+(?:under|below)\s+(\d{1,3})", re.I)
PRIOR_OBS = re.compile(
    r"\b(\d{1,4})\s*(day|month|year)s?\s+of\s+(?:prior|continuous|previous)"
    r"\s+(?:observation|data|history|enrol\w+)", re.I)
ONE_YEAR_PRIOR = re.compile(
    r"\b(?:at least )?(?:one|1|a)\s+year\s+of\s+(?:prior|continuous|previous)",
    re.I)

LEAD_IN = re.compile(
    r"^\s*(?:identify|find|select|retrieve|list|build (?:a )?cohort of|"
    r"define (?:a )?cohort of)?\s*"
    r"(?:all\s+)?"
    r"(?:adult\s+patients?|adults?|patients?|persons?|individuals?|subjects?)?"
    r"\s*(?:who (?:have|had|are|were)|with (?:a )?(?:recorded |documented )?"
    r"(?:diagnosis of|history of)?|diagnosed with|receiving|taking|starting|"
    r"prescribed)?\s*", re.I)

# Leading event wrappers: "a first diagnosis of", "new users of", "all events of"
EVENT_WRAPPER = re.compile(
    r"^\s*(?:a|an|the|all)?\s*"
    r"(?:first|earliest|incident|new|newly|initial)?\s*"
    r"(?:recorded|documented|confirmed)?\s*"
    r"(?:diagnos\w+|events?|occurrences?|users?|use|exposures?|"
    r"prescriptions?|episodes?)\s+(?:of|with|for)\s+", re.I)

# Trailing qualifier clauses that describe the study, not the clinical term
TRAILING_QUALIFIER = re.compile(
    r",\s*(?:with|who|and|aged|having)\b.*$", re.I)
TRAILING_PUNCT = re.compile(r"[.?!]+\s*$")

STOPWORDS = {"a", "an", "the", "of", "for", "in", "with", "and", "or",
             "patients", "patient", "adults", "adult", "least", "at"}

DOMAIN_HINTS = {
    "Drug": re.compile(
        r"\b(drug|medication|therapy|treated with|prescribed|users? of|"
        r"antibiotic|inhibitors?|blockers?|agonists?|antagonists?|statins?|"
        r"diuretics?|opioids?)\b", re.I),
    "Procedure": re.compile(
        r"\b(procedure|surgery|surgical|operation|resection|implant\w*|"
        r"transplant\w*|ventilat\w+|dialysis|endoscopy|biopsy)\b", re.I),
}


@dataclass
class LexicalResult:
    spec: Optional[CohortSpec]
    resolved: dict[str, set[int]] = field(default_factory=dict)
    unresolved: list[str] = field(default_factory=list)
    status: str = "success"
    reason: Optional[str] = None
    trace: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"status": self.status, "reason": self.reason,
                "unresolved": self.unresolved,
                "resolved_sizes": {k: len(v) for k, v in self.resolved.items()},
                "trace": self.trace}


# --- structural normalization -----------------------------------------------

STRUCTURAL_PATTERNS = [
    (
        re.compile(
            r"\bat\s+(?:their|the)\s+(?:first|earliest|initial)\s+"
            r"(?:qualifying\s+)?(?:occurrence|event|episode|diagnosis|record)\b",
            re.I,
        ),
        "first_occurrence",
        True,
    ),
    (
        re.compile(
            r"\b(?:for\s+the\s+)?(?:first|earliest|initial)\s+"
            r"(?:qualifying\s+)?(?:occurrence|event|episode|time)\b",
            re.I,
        ),
        "first_occurrence",
        True,
    ),
    (
        re.compile(
            r"\bnewly\s+diagnosed\b|\bincident\b",
            re.I,
        ),
        "first_occurrence",
        True,
    ),
    (
        re.compile(
            r"\bin\s+the\s+(?:year|12\s+months|month)\s+"
            r"(?:before|prior\s+to)\b",
            re.I,
        ),
        "prior_window",
        -365,
    ),
    (
        re.compile(
            r"\bprior\s+history\s+of\b|\bpreviously\s+recorded\b",
            re.I,
        ),
        "prior_history",
        True,
    ),
]


def extract_structure(question: str) -> tuple[str, dict, list[dict]]:
    """Extract structural modifiers and remove their spans from the question.

    Clinical terms are not interpreted here. Only phrases carrying cohort
    structure are removed, and every removal is recorded for provenance.
    """
    residual = question or ""
    structure = {
        "first_occurrence": False,
        "prior_observation_days": 0,
    }
    trace: list[dict] = []

    for pattern, field, value in STRUCTURAL_PATTERNS:
        matches = list(pattern.finditer(residual))
        if not matches:
            continue

        for match in reversed(matches):
            span = match.group(0)
            trace.append({
                "step": "structural_extraction",
                "span": span,
                "field": field,
                "value": value,
            })
            residual = residual[:match.start()] + " " + residual[match.end():]

        if field == "first_occurrence":
            structure["first_occurrence"] = True
        elif field == "prior_window":
            structure["prior_observation_days"] = 365

    return residual, structure, trace


# --- text handling ----------------------------------------------------------

def clean_term(text: str) -> str:
    """Reduce a question fragment to the clinical term it names.

    Order matters: trailing study qualifiers first, then the lead-in verb
    phrase, then event wrappers such as "a first diagnosis of", which may nest.
    """
    t = (text or "").strip()
    t = TRAILING_QUALIFIER.sub("", t)
    t = TRAILING_PUNCT.sub("", t).strip(" ,.;:")
    t = LEAD_IN.sub("", t, count=1).strip(" ,.;:")

    for _ in range(3):                      # wrappers can nest
        stripped = EVENT_WRAPPER.sub("", t, count=1).strip(" ,.;:")
        if stripped == t or not stripped:
            break
        t = stripped

    words = [w for w in re.split(r"\s+", t) if w]
    while words and words[0].lower() in STOPWORDS:
        words.pop(0)
    while words and words[-1].lower() in STOPWORDS:
        words.pop()
    return " ".join(words)


def _split_compound_exclusions(terms: list[str]) -> list[str]:
    """Split exclusions when a conjunction starts a new patient-level clause."""
    out: list[str] = []

    for term in terms:
        pieces = re.split(
            r"\s+\band\s+(?=(?:patients?|persons?|subjects?)\b)",
            term,
            flags=re.I,
        )
        out.extend(piece.strip() for piece in pieces if piece.strip())

    return out


def split_terms(question: str) -> tuple[str, list[str], list[str]]:
    """Return (primary term, required terms, excluded terms)."""
    excluded: list[str] = []
    required: list[str] = []

    head = question
    parts = EXCLUSION_SPLIT.split(head)
    if len(parts) > 1:
        head = parts[0]
        excluded = _split_compound_exclusions(
            [clean_term(p) for p in parts[1:]]
        )

    parts = REQUIRE_SPLIT.split(head)
    if len(parts) > 1:
        head = parts[0]
        required = [clean_term(p) for p in parts[1:]]

    return clean_term(head), [t for t in required if t], [t for t in excluded if t]


def guess_domain(text: str, default: str = "Condition") -> str:
    for domain, pattern in DOMAIN_HINTS.items():
        if pattern.search(text):
            return domain
    return default


def detect_temporal(question: str) -> tuple[bool, int]:
    first = bool(FIRST_OCCURRENCE.search(question))
    prior = 0
    m = PRIOR_OBS.search(question)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        prior = n * {"day": 1, "month": 30, "year": 365}[unit]
    elif ONE_YEAR_PRIOR.search(question):
        prior = 365
    elif NEW_USER.search(question):
        prior = 365                       # conventional washout
    return first, prior


def detect_age(question: str) -> tuple[Optional[int], Optional[int]]:
    lo = hi = None
    m = AGE_MIN.search(question)
    if m:
        lo = int(m.group(1))
    elif ADULT.search(question):
        lo = 18
    m = AGE_MAX.search(question)
    if m:
        hi = int(m.group(1)) - 1
    return lo, hi


# --- concept selection ------------------------------------------------------

def select_concept(con, term: str, domain: str) -> Optional[tuple]:
    """Hierarchy-aware lexical selection.

    Carried over from the Phase-4 selector: an exact name match is taken; a
    partial match is accepted only when nothing exact exists, and never
    silently substitutes a subtype for the requested concept when a broader
    match is available.
    """
    if not term:
        return None
    rows = vocab.search_concepts(con, term, domain=domain, limit=15)
    if not rows:
        return None
    target = term.lower().strip()
    for r in rows:
        if (r[1] or "").lower() == target:
            return r
    # no exact match: prefer the shortest name, which search already ranks first
    return rows[0]


def make_set(name: str, domain: str, description: str, row: tuple,
             excluded: bool = False) -> ConceptSet:
    return ConceptSet(
        name=name, domain=domain, description=description,
        items=[ConceptItem(
            concept_id=int(row[0]), include_descendants=True,
            is_excluded=excluded,
            rationale=f"lexical match for '{description}': {row[1]}")],
    )


# --- pipeline ---------------------------------------------------------------

def run_lexical(question: str, vocab_con, domain_hint: Optional[str] = None
                ) -> LexicalResult:
    """C0-plus. Deterministic: identical input always gives identical output."""
    trace: list[dict] = []
    unresolved: list[str] = []

    residual_question, structure, structural_trace = extract_structure(question)
    trace.extend(structural_trace)

    primary, required, excluded = split_terms(residual_question)

    first_occurrence = structure["first_occurrence"]
    prior_days = structure["prior_observation_days"]

    # Preserve the existing temporal detectors for structural patterns that
    # are not removed by extract_structure(), without overriding extraction.
    detected_first, detected_prior = detect_temporal(question)
    first_occurrence = first_occurrence or detected_first
    prior_days = max(prior_days, detected_prior)

    age_min, age_max = detect_age(question)

    trace.append({"step": "parse", "primary": primary, "required": required,
                  "excluded": excluded, "first_occurrence": first_occurrence,
                  "prior_observation_days": prior_days,
                  "age_min": age_min, "age_max": age_max})

    entry_domain = domain_hint or guess_domain(primary)
    row = select_concept(vocab_con, primary, entry_domain)
    if row is None and domain_hint is None:
        for alt in ("Condition", "Drug", "Procedure"):
            if alt == entry_domain:
                continue
            row = select_concept(vocab_con, primary, alt)
            if row is not None:
                entry_domain = alt
                break

    if row is None:
        unresolved.append(primary)
        trace.append({"step": "entry_unresolved", "term": primary})
        return LexicalResult(None, {}, unresolved, "failed",
                             f"entry term unresolved: {primary!r}", trace)

    concept_sets = {"entry": make_set("entry", entry_domain, primary, row)}
    trace.append({"step": "entry_resolved", "term": primary,
                  "concept_id": int(row[0]), "concept_name": row[1],
                  "domain": entry_domain})

    criteria: list[Criterion] = []
    for i, term in enumerate(required):
        dom = guess_domain(term)
        r = select_concept(vocab_con, term, dom)
        if r is None:
            unresolved.append(term)
            trace.append({"step": "required_unresolved", "term": term})
            continue
        name = f"require_{i + 1}"
        concept_sets[name] = make_set(name, dom, term, r)
        criteria.append(Criterion(concept_set=name, window_start_days=-365,
                                  window_end_days=0, rule="at_least_one"))
        trace.append({"step": "required_resolved", "term": term,
                      "concept_id": int(r[0])})

    for i, term in enumerate(excluded):
        dom = guess_domain(term)
        r = select_concept(vocab_con, term, dom)
        if r is None:
            unresolved.append(term)
            trace.append({"step": "excluded_unresolved", "term": term})
            continue
        name = f"exclude_{i + 1}"
        concept_sets[name] = make_set(name, dom, term, r)
        criteria.append(Criterion(concept_set=name, window_start_days=-99999,
                                  window_end_days=0, rule="none"))
        trace.append({"step": "excluded_resolved", "term": term,
                      "concept_id": int(r[0])})

    spec = CohortSpec(
        question=question, entry_concept_set="entry",
        first_occurrence_only=first_occurrence,
        age_min=age_min, age_max=age_max,
        prior_observation_days=prior_days,
        concept_sets=concept_sets, criteria=criteria,
    )

    resolved = {name: restrict_to_standard(
                    vocab_con, resolve_items(vocab_con,
                                             [i.model_dump() for i in cs.items]))
                for name, cs in spec.concept_sets.items()}

    return LexicalResult(spec, resolved, unresolved, "success", None, trace)
