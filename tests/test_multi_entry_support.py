"""Small regression tests for the multi-entry patch. Run from the project root:
PYTHONPATH=. .venv/bin/python -m unittest discover -s tests -p 'test_multi_entry_support.py'
"""
import unittest

from src.schema.spec import CohortSpec, ConceptItem, ConceptSet, EntryArm
from src.tools.compiler import compile_spec, required_temp_tables
from src.tools.validator import validate


def concept_set(name, domain, concept_id):
    return ConceptSet(
        name=name,
        domain=domain,
        description=f"Test {name} concepts",
        items=[ConceptItem(concept_id=concept_id, rationale="test entry concept")],
    )


class MultiEntryTests(unittest.TestCase):
    def setUp(self):
        self.sets = {
            "diagnosis": concept_set("diagnosis", "Condition", 201826),
            "treatment": concept_set("treatment", "Drug", 19019073),
        }

    def test_legacy_single_entry_still_normalizes(self):
        spec = CohortSpec(
            entry_concept_set="diagnosis",
            concept_sets={"diagnosis": self.sets["diagnosis"]},
        )
        self.assertEqual(spec.entry_concept_sets, ["diagnosis"])
        self.assertIn("condition_occurrence", compile_spec(spec))

    def test_multi_entry_compiles_as_cross_domain_or(self):
        spec = CohortSpec(
            entry_concept_sets=["diagnosis", "treatment"],
            concept_sets=self.sets,
        )
        sql = compile_spec(spec)
        self.assertIn("condition_occurrence", sql)
        self.assertIn("drug_exposure", sql)
        self.assertIn("UNION ALL", sql)
        self.assertEqual(
            set(required_temp_tables(spec)), {"diagnosis", "treatment"}
        )

    def test_validator_checks_all_entry_arms(self):
        spec = CohortSpec(
            entry_concept_sets=["diagnosis", "treatment"],
            concept_sets=self.sets,
        )
        result = validate(spec, resolved={"diagnosis": {201826}, "treatment": set()})
        self.assertTrue(any(
            issue.code == "entry_set_resolves_empty" and issue.concept_set == "treatment"
            for issue in result.errors
        ))


class EventArmRegressionTests(unittest.TestCase):
    def test_planner_output_preserves_explicit_multi_event_arms(self):
        from src.schema.spec import PlannerOutput

        payload = {
            "entry_concept_set": "shared",
            "entry_concept_sets": ["shared"],
            "entry_arms": [
                {"concept_set": "shared", "event_domain": "Condition"},
                {"concept_set": "shared", "event_domain": "Procedure"},
            ],
            "concept_sets": {
                "shared": {
                    "name": "shared",
                    "domain": "Condition",
                    "description": "The clinical event defining cohort entry.",
                    "items": [],
                }
            },
        }

        spec = PlannerOutput(**payload).to_spec(question="Regression test")
        self.assertEqual(spec.entry_concept_sets, ["shared"])
        self.assertEqual(
            [(arm.concept_set, arm.event_domain) for arm in spec.entry_arms],
            [("shared", "Condition"), ("shared", "Procedure")],
        )

        restored = type(spec).model_validate(spec.model_dump())
        self.assertEqual(
            [(arm.concept_set, arm.event_domain) for arm in restored.entry_arms],
            [("shared", "Condition"), ("shared", "Procedure")],
        )

    def test_entry_domain_uses_event_arm_not_vocabulary_domain(self):
        spec = CohortSpec(
            entry_concept_sets=["shared"],
            entry_arms=[
                EntryArm(concept_set="shared", event_domain="Procedure")
            ],
            concept_sets={
                "shared": concept_set("shared", "Condition", 201826)
            },
        )
        self.assertEqual(spec.concept_sets["shared"].domain, "Condition")
        self.assertEqual(spec.entry_domain, "Procedure")

    def test_legacy_entry_normalizes_and_round_trips(self):
        spec = CohortSpec(
            entry_concept_set="diagnosis",
            concept_sets={"diagnosis": concept_set("diagnosis", "Condition", 201826)},
        )
        self.assertEqual(len(spec.entry_arms), 1)
        self.assertEqual(spec.entry_arms[0].concept_set, "diagnosis")
        self.assertEqual(spec.entry_arms[0].event_domain, "Condition")

        restored = CohortSpec.model_validate(spec.model_dump())
        self.assertEqual(restored.model_dump(), spec.model_dump())

    def test_all_seven_event_domains_compile_to_expected_columns(self):
        from src.schema.spec import EntryArm

        cases = {
            "Condition": ("condition_occurrence", "condition_concept_id", "condition_start_date"),
            "Drug": ("drug_exposure", "drug_concept_id", "drug_exposure_start_date"),
            "Procedure": ("procedure_occurrence", "procedure_concept_id", "procedure_date"),
            "Measurement": ("measurement", "measurement_concept_id", "measurement_date"),
            "Observation": ("observation", "observation_concept_id", "observation_date"),
            "Visit": ("visit_occurrence", "visit_concept_id", "visit_start_date"),
            "Device": ("device_exposure", "device_concept_id", "device_exposure_start_date"),
        }
        for domain, expected in cases.items():
            with self.subTest(domain=domain):
                cs = concept_set("shared", "Condition", 201826)
                spec = CohortSpec(
                    entry_concept_sets=["shared"],
                    entry_arms=[EntryArm(concept_set="shared", event_domain=domain)],
                    concept_sets={"shared": cs},
                )
                sql = compile_spec(spec)
                table, concept_col, date_col = expected
                self.assertIn(f"FROM {table} t", sql)
                self.assertIn(f"t.{concept_col}", sql)
                self.assertIn(f"t.{date_col} AS event_date", sql)

    def test_same_set_can_be_reused_across_event_domains(self):
        from src.schema.spec import EntryArm

        cs = concept_set("shared", "Condition", 201826)
        spec = CohortSpec(
            entry_concept_sets=["shared"],
            entry_arms=[
                EntryArm(concept_set="shared", event_domain="Condition"),
                EntryArm(concept_set="shared", event_domain="Procedure"),
            ],
            concept_sets={"shared": cs},
        )
        sql = compile_spec(spec)
        self.assertIn("FROM condition_occurrence t", sql)
        self.assertIn("FROM procedure_occurrence t", sql)
        self.assertEqual(sql.count("JOIN cs_shared s"), 2)
        self.assertEqual(len(required_temp_tables(spec)), 1)

    def test_unsupported_event_domain_is_rejected(self):
        from pydantic import ValidationError
        from src.schema.spec import EntryArm

        with self.assertRaises(ValidationError):
            EntryArm(concept_set="shared", event_domain="Demographic")

    def test_non_entry_vocabulary_domain_mismatch_is_still_reported(self):
        entry = concept_set("diagnosis", "Condition", 201826)
        other = concept_set("other", "Drug", 19019073)
        spec = CohortSpec(
            entry_concept_set="diagnosis",
            concept_sets={"diagnosis": entry, "other": other},
        )

        class FakeCursor:
            def fetchall(self):
                return [
                    (201826, "Condition", "S", None),
                    (19019073, "Condition", "S", None),
                ]

        class FakeVocabulary:
            def execute(self, query, ids):
                return FakeCursor()

        result = validate(spec, vocab_con=FakeVocabulary())
        self.assertTrue(any(
            issue.code == "domain_mismatch"
            and issue.concept_set == "other"
            and issue.concept_id == 19019073
            for issue in result.errors
        ))


if __name__ == "__main__":
    unittest.main()
