"""Diagnostic regression test for cross-domain shared-codeset routing.

This test documents current compiler behavior; it does not endorse that
behavior as clinically correct. It uses an in-memory DuckDB only.
"""
import unittest
import duckdb

from src.schema.spec import CohortSpec, ConceptSet, ConceptItem, EntryArm
from src.tools.compiler import compile_spec, required_temp_tables


class EntryDomainRoutingDiagnosticTests(unittest.TestCase):
    def test_shared_codeset_can_let_cross_domain_event_set_index_date(self):
        spec = CohortSpec(
            entry_concept_sets=["shared"],
            entry_arms=[
                EntryArm(concept_set="shared", event_domain="Condition"),
                EntryArm(concept_set="shared", event_domain="Procedure"),
            ],
            first_occurrence_only=True,
            concept_sets={
                "shared": ConceptSet(
                    name="shared",
                    domain="Condition",
                    description="Synthetic domain-routing diagnostic",
                    items=[
                        ConceptItem(
                            concept_id=101,
                            include_descendants=False,
                            rationale="Synthetic condition concept for routing test",
                        )
                    ],
                )
            },
        )

        con = duckdb.connect(":memory:")
        try:
            con.execute("""
                CREATE TABLE person(
                    person_id BIGINT, year_of_birth INTEGER,
                    gender_concept_id BIGINT
                )
            """)
            con.execute("""
                CREATE TABLE observation_period(
                    person_id BIGINT, observation_period_start_date DATE,
                    observation_period_end_date DATE
                )
            """)
            con.execute("""
                CREATE TABLE condition_occurrence(
                    person_id BIGINT, condition_concept_id BIGINT,
                    condition_start_date DATE
                )
            """)
            con.execute("""
                CREATE TABLE procedure_occurrence(
                    person_id BIGINT, procedure_concept_id BIGINT,
                    procedure_date DATE
                )
            """)
            con.execute("INSERT INTO person VALUES (1, 1980, 8507)")
            con.execute("""
                INSERT INTO observation_period VALUES
                (1, DATE '2020-01-01', DATE '2025-01-01')
            """)
            con.execute("""
                INSERT INTO condition_occurrence VALUES
                (1, 101, DATE '2022-01-01')
            """)
            con.execute("""
                INSERT INTO procedure_occurrence VALUES
                (1, 101, DATE '2021-01-01')
            """)

            con.execute("CREATE TEMP TABLE cs_shared(concept_id BIGINT)")
            con.execute("INSERT INTO cs_shared VALUES (101)")

            sql = compile_spec(spec)
            result = con.execute(sql).fetchall()

            self.assertEqual(required_temp_tables(spec), {"shared": "cs_shared"})
            self.assertEqual(sql.count("JOIN cs_shared s"), 2)
            # Documents current behavior: both arms use the same IDs, so the
            # earlier synthetic Procedure date becomes the first index date.
            self.assertEqual(len(result), 1)
            self.assertEqual(str(result[0][1]), "2021-01-01")
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
