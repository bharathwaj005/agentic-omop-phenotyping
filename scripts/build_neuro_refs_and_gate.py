"""Build Neuro-track references in a SEPARATE folder and run the entry-Jaccard gate.
Never writes to V5.3 reference folders. Never overwrites existing files."""
import json, hashlib, itertools, sys
from pathlib import Path
import pandas as pd
from src import paths
from src.tools.resolver import open_vocab
from src.eval.build_reference import build_one   # import only; main() is NOT run

HDD       = Path("/media/bharathwaj/HDD_Storage/project_jbi")
RAW_DIR   = HDD / "tasks" / "reference_raw"
OUT_DIR   = Path("tasks/reference_neuro")
V53_DIRS  = [Path("tasks/reference"), HDD / "tasks" / "reference"]
AUDIT_DIR = Path("results/benchmark_design/NEURO_AUDIT")
THRESHOLD = 0.90

NEURO_IDS = [255, 33, 863, 552, 1026, 287, 535, 1079, 544, 235, 1080, 550, 229, 1066]
V53_IDS   = [134, 219, 290, 334, 373, 588, 785, 862, 864, 967,
             1048, 1064, 1073, 1183, 1184, 1188, 1261, 1263, 1285, 1301]

# ---------- Safety check ----------
forbidden = {Path(paths.REFERENCE_DIR).resolve()} | {d.resolve() for d in V53_DIRS}
if OUT_DIR.resolve() in forbidden:
    sys.exit("ABORT: output folder is a V5.3 reference folder.")
OUT_DIR.mkdir(parents=True, exist_ok=True)
AUDIT_DIR.mkdir(parents=True, exist_ok=True)

# ---------- Step 1: build neuro references ----------
print("=== STEP 1: BUILD NEURO REFERENCES ===")
with open_vocab() as con:
    for cid in NEURO_IDS:
        out = OUT_DIR / f"{cid}.json"
        if out.exists():
            print(f"  [skip] {cid}: already exists (not overwritten)")
            continue
        raw_f = RAW_DIR / f"{cid}.json"
        if not raw_f.exists():
            print(f"  [miss] {cid}: not in reference_raw")
            continue
        ref = build_one(con, json.loads(raw_f.read_text()), str(cid))
        out.write_text(json.dumps(ref, indent=1))
        flag = "  <-- EMPTY ENTRY SET" if ref["counts"]["entry"] == 0 else ""
        print(f"  [ok]   {cid:<5} entry={ref['counts']['entry']:>5}  all={ref['counts']['all']:>5}{flag}")

# ---------- Step 2: load entry sets ----------
def load_entry(cid, dirs):
    for d in dirs:
        f = d / f"{cid}.json"
        if f.exists():
            return set(json.loads(f.read_text())["entry_concept_ids"])
    return None

neuro = {c: s for c in NEURO_IDS if (s := load_entry(c, [OUT_DIR])) is not None}
v53   = {c: s for c in V53_IDS   if (s := load_entry(c, V53_DIRS)) is not None}
print(f"\nLoaded neuro refs: {len(neuro)}/{len(NEURO_IDS)}   V5.3 refs: {len(v53)}/{len(V53_IDS)}")

def jac(a, b):
    u = a | b
    return round(len(a & b) / len(u), 6) if u else None

rows = []
for n, s in neuro.items():
    for v, t in v53.items():
        rows.append({"neuro_id": n, "other_id": v, "other_set": "V5.3",
                     "jaccard": jac(s, t), "overlap": len(s & t), "union": len(s | t)})
for a, b in itertools.combinations(neuro, 2):
    rows.append({"neuro_id": a, "other_id": b, "other_set": "NEURO",
                 "jaccard": jac(neuro[a], neuro[b]),
                 "overlap": len(neuro[a] & neuro[b]), "union": len(neuro[a] | neuro[b])})

df = pd.DataFrame(rows).sort_values("jaccard", ascending=False, na_position="last")
df.to_csv(AUDIT_DIR / "NEURO_ENTRY_JACCARD_PAIRS.csv", index=False)

# ---------- Step 3: gate summary ----------
print(f"\n=== STEP 3: GATE SUMMARY (threshold {THRESHOLD}) ===")
lines = []
for n in neuro:
    sub = df[(df.neuro_id == n) | ((df.other_id == n) & (df.other_set == "NEURO"))].dropna(subset=["jaccard"])
    if sub.empty:
        lines.append(f"  {n:<5} no comparable pairs"); continue
    top = sub.iloc[0]
    partner = top.other_id if top.neuro_id == n else top.neuro_id
    status = "FAIL" if top.jaccard >= THRESHOLD else "PASS"
    lines.append(f"  {n:<5} max={top.jaccard:<9} vs {partner:<5} ({top.other_set})  {status}")
print("\n".join(lines))

print("\nTop 10 pairs overall:")
print(df.head(10).to_string(index=False))

with open(AUDIT_DIR / "NEURO_GATE_SUMMARY.txt", "w") as f:
    f.write(f"Threshold: {THRESHOLD}\n" + "\n".join(lines) + "\n\nReference SHA256:\n")
    for p in sorted(OUT_DIR.glob("*.json")):
        f.write(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p}\n")
print(f"\nSaved: {AUDIT_DIR}/NEURO_ENTRY_JACCARD_PAIRS.csv and NEURO_GATE_SUMMARY.txt")
print("=== DONE ===")

