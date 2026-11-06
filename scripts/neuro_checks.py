"""Read-only neuro feasibility checks for the JBI Neuro track."""
import duckdb, pandas as pd

EUN  = "data/eunomia.duckdb"
VOC  = "data/vocab.duckdb"
POOL = "results/benchmark_design/FULL_BENCHMARK_POOL.csv"

COND_TERMS = ["alzheimer", "dementia", "mild cognitive", "parkinson",
              "multiple sclerosis", "neuromyelitis", "demyelinat",
              "encephalitis", "guillain", "polyneuropathy"]
DRUG_TERMS = ["donepezil", "rivastigmine", "galantamine", "memantine",
              "lecanemab", "donanemab", "aducanumab", "natalizumab",
              "ocrelizumab", "fingolimod", "interferon beta", "glatiramer",
              "adalimumab", "infliximab", "etanercept"]
MEAS_TERMS = ["c reactive protein", "erythrocyte sedimentation"]

def run(con, sql, params):
    try:
        return con.execute(sql, params).fetchone()[0]
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"

# ---------- 1. Eunomia patient counts ----------
print("\n=== 1. EUNOMIA PATIENT COUNTS ===")
con = duckdb.connect(EUN, read_only=True)
con.execute(f"ATTACH '{VOC}' AS v (READ_ONLY)")

checks = [("condition_occurrence", "condition_concept_id", COND_TERMS),
          ("drug_exposure",        "drug_concept_id",      DRUG_TERMS),
          ("measurement",          "measurement_concept_id", MEAS_TERMS)]
for table, col, terms in checks:
    print(f"\n-- {table} --")
    for t in terms:
        n = run(con, f"""SELECT COUNT(DISTINCT x.person_id) FROM {table} x
                         JOIN v.concept c ON c.concept_id = x.{col}
                         WHERE lower(c.concept_name) LIKE ?""", [f"%{t}%"])
        print(f"  {t:28s} patients = {n}")
con.close()

# ---------- 2. Athena standard concepts ----------
print("\n=== 2. ATHENA STANDARD CONCEPTS ===")
vcon = duckdb.connect(VOC, read_only=True)
for t in COND_TERMS + DRUG_TERMS + MEAS_TERMS:
    try:
        rows = vcon.execute("""SELECT domain_id, vocabulary_id, COUNT(*) FROM concept
                               WHERE lower(concept_name) LIKE ? AND standard_concept='S'
                               GROUP BY 1,2 ORDER BY 3 DESC LIMIT 3""",
                            [f"%{t}%"]).fetchall()
    except Exception as e:
        rows = f"ERROR: {e}"
    print(f"  {t:28s} -> {rows if rows else 'NOT FOUND'}")
vcon.close()

# ---------- 3. Benchmark pool search ----------
print("\n=== 3. BENCHMARK POOL NEURO MATCHES ===")
df = pd.read_csv(POOL)
print("Pool columns:", list(df.columns))
pat = ("alzheimer|dementia|cognitive|parkinson|sclerosis|neuromyelitis|"
       "demyelin|encephal|guillain|donepezil|memantine|galantamine|rivastigmine|"
       "natalizumab|tnf|inflammat")
mask = df.astype(str).apply(lambda c: c.str.contains(pat, case=False, regex=True)).any(axis=1)
hits = df[mask]
print(f"Matching cohorts: {len(hits)} of {len(df)}")
out = "results/benchmark_design/NEURO_POOL_MATCHES.csv"
hits.to_csv(out, index=False)
print(f"Saved matches to {out}")
with pd.option_context("display.max_colwidth", 60, "display.width", 200):
    print(hits.head(60).to_string())
print("\n=== NEURO CHECKS COMPLETE ===")
