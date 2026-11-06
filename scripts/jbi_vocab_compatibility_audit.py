#!/usr/bin/env python3
"""
Read-only OMOP vocabulary compatibility audit for the JBI project.

Audits tasks/reference_raw_v2/*.json against data/vocab.duckdb.
Optionally scans local ZIP archives for missing concept IDs and exports any
exact matching CONCEPT.csv rows as a supplemental evidence file.

This script NEVER edits the vocabulary database, reference JSONs, or benchmark
queue. It does not substitute concepts or recalculate benchmark scores.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import time
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

try:
    import duckdb
except ImportError:
    print("ERROR: duckdb is not installed in the active Python environment.")
    print("Run: source ~/jbi/.venv/bin/activate")
    raise SystemExit(2)

DEFAULT_ROOT = Path.home() / "jbi"
DEFAULT_REF = Path("/media/bharathwaj/HDD_Storage/project_jbi/tasks/reference_raw_v2")
DEFAULT_DB = DEFAULT_ROOT / "data/vocab.duckdb"
DEFAULT_OUT_ROOT = Path("/media/bharathwaj/HDD_Storage/project_jbi/results/benchmark_design")
DEFAULT_ARCHIVE_ROOTS = [
    Path("/media/bharathwaj/HDD_Storage"),
    Path.home() / "Downloads",
]

def safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

def read_reference_occurrences(ref_dir: Path):
    """Read legacy item-based and V2 concept-ID-list reference schemas."""
    occurrences = []
    json_files = sorted(ref_dir.glob("*.json"))

    for path in json_files:
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[WARN] Could not parse {path.name}: {exc}")
            continue
        if not isinstance(obj, dict):
            continue

        cohort_id = str(obj.get("cohort_id", path.stem))
        entry_codesets = {str(x) for x in obj.get("entry_codeset_ids", [])}
        entry_arms = obj.get("entry_arms", [])
        domains_by_codeset = defaultdict(set)

        for arm in entry_arms:
            if isinstance(arm, dict) and arm.get("codeset_id") is not None:
                domain = str(arm.get("domain", "") or "")
                if domain:
                    domains_by_codeset[str(arm["codeset_id"])].add(domain)

        concept_sets = obj.get("concept_sets", {})
        if not isinstance(concept_sets, dict):
            continue

        for codeset_id, codeset in concept_sets.items():
            if not isinstance(codeset, dict):
                continue

            code_key = str(codeset_id)
            codeset_name = str(codeset.get("name", "") or "")
            entry_domains = sorted(domains_by_codeset.get(code_key, set()))
            entry_domain_text = ";".join(entry_domains)

            # Legacy format: concept dictionaries inside an items list.
            items = codeset.get("items")
            if isinstance(items, list):
                for item_index, item in enumerate(items):
                    if not isinstance(item, dict):
                        continue
                    cid = safe_int(item.get("concept_id"))
                    if cid is None:
                        continue
                    occurrences.append({
                        "cohort_id": cohort_id,
                        "source_file": path.name,
                        "codeset_id": code_key,
                        "codeset_name": codeset_name,
                        "item_index": item_index,
                        "concept_id": cid,
                        "source_concept_name": str(item.get("concept_name", "") or ""),
                        "source_domain": str(item.get("domain_id", "") or ""),
                        "source_standard_concept": str(item.get("standard_concept", "") or ""),
                        "include_descendants": bool(item.get("include_descendants", False)),
                        "include_mapped": bool(item.get("include_mapped", False)),
                        "is_excluded": bool(item.get("is_excluded", False)),
                        "is_entry_codeset": code_key in entry_codesets,
                        "entry_arm_domains": entry_domain_text,
                    })
                continue

            # V2 format: concept_ids is a list of integer IDs. V2 does not
            # retain per-ID source names or source vocabulary metadata here.
            ids = codeset.get("concept_ids")
            if isinstance(ids, list):
                # Only assign a source domain when the codeset maps to one
                # unambiguous domain. Never guess across multiple entry arms.
                source_domain = entry_domains[0] if len(entry_domains) == 1 else ""
                for item_index, value in enumerate(ids):
                    cid = safe_int(value)
                    if cid is None:
                        continue
                    occurrences.append({
                        "cohort_id": cohort_id,
                        "source_file": path.name,
                        "codeset_id": code_key,
                        "codeset_name": codeset_name,
                        "item_index": item_index,
                        "concept_id": cid,
                        "source_concept_name": "",
                        "source_domain": source_domain,
                        "source_standard_concept": "",
                        "include_descendants": False,
                        "include_mapped": False,
                        "is_excluded": False,
                        "is_entry_codeset": code_key in entry_codesets,
                        "entry_arm_domains": entry_domain_text,
                    })

    return json_files, occurrences

def lookup_vocab(db_path: Path, concept_ids):
    """Query DuckDB read-only using a temporary table of IDs."""
    if not db_path.exists():
        raise FileNotFoundError(f"Vocabulary DB not found: {db_path}")
    unique_ids = sorted(set(concept_ids))
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        con.execute("CREATE TEMP TABLE audit_ids(concept_id BIGINT)")
        con.executemany("INSERT INTO audit_ids VALUES (?)", [(x,) for x in unique_ids])
        rows = con.execute("""
            SELECT c.concept_id, c.concept_name, c.domain_id, c.vocabulary_id,
                   c.concept_class_id, c.standard_concept, c.concept_code,
                   CAST(c.valid_start_date AS VARCHAR),
                   CAST(c.valid_end_date AS VARCHAR), c.invalid_reason
            FROM concept c
            JOIN audit_ids a USING (concept_id)
        """).fetchall()
        columns = [d[0] for d in con.description]
        return {int(row[0]): dict(zip(columns, row)) for row in rows}
    finally:
        con.close()

def primary_status(source, dbrow):
    if dbrow is None:
        return "MISSING_FROM_CURRENT_VOCABULARY"
    flags = []
    invalid_reason = dbrow.get("invalid_reason")
    if invalid_reason not in (None, ""):
        flags.append("INVALID")
    if dbrow.get("standard_concept") != "S":
        flags.append("NOT_STANDARD")
    source_domain = (source.get("source_domain") or "").strip().lower()
    db_domain = (dbrow.get("domain_id") or "").strip().lower()
    if source_domain and db_domain and source_domain != db_domain:
        flags.append("DOMAIN_MISMATCH")
    if not flags:
        return "PRESENT_VALID_STANDARD_DOMAIN_MATCH"
    return "+".join(flags)

def csv_write(path: Path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

def find_zip_candidates(roots):
    found = []
    seen = set()
    for root in roots:
        if not root.exists():
            continue
        # Do not recursively descend into hidden app caches; search ordinary ZIPs.
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in {
                ".cache", ".local", ".venv", "node_modules"
            }]
            for name in filenames:
                if name.lower().endswith(".zip"):
                    p = Path(dirpath) / name
                    try:
                        key = str(p.resolve())
                        size = p.stat().st_size
                    except OSError:
                        continue
                    if key not in seen:
                        seen.add(key)
                        found.append((p, size))
    return sorted(found, key=lambda x: x[0].as_posix())

def scan_archive_for_ids(zip_path: Path, wanted_ids):
    """Stream CONCEPT.csv inside one ZIP; return exact matching records."""
    matches = {}
    try:
        with zipfile.ZipFile(zip_path) as zf:
            members = [n for n in zf.namelist()
                       if n.replace("\\", "/").split("/")[-1].upper() == "CONCEPT.CSV"]
            if not members:
                return matches, "NO_CONCEPT_CSV"
            # If multiple, inspect each; preserve first row per ID and source member.
            for member in members:
                with zf.open(member) as raw:
                    text = io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace", newline="")
                    reader = csv.DictReader(text, delimiter="\t")
                    if not reader.fieldnames or "concept_id" not in reader.fieldnames:
                        continue
                    for row in reader:
                        cid = safe_int(row.get("concept_id"))
                        if cid in wanted_ids and cid not in matches:
                            matches[cid] = {
                                **row,
                                "_archive": str(zip_path),
                                "_member": member,
                            }
                            if len(matches) == len(wanted_ids):
                                return matches, "SCANNED"
        return matches, "SCANNED"
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        return matches, f"ERROR:{exc}"

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reference-dir", type=Path, default=DEFAULT_REF)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    ap.add_argument("--scan-archives", action="store_true",
                    help="also stream local ZIPs looking for IDs missing from DuckDB")
    ap.add_argument("--archive-root", action="append", type=Path, default=None,
                    help="ZIP search root; can be supplied multiple times")
    args = ap.parse_args()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = args.out_root / f"VOCAB_COMPAT_AUDIT_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=False)

    print("=== JBI VOCABULARY COMPATIBILITY AUDIT ===")
    print(f"Reference source : {args.reference_dir}")
    print(f"Vocabulary DB   : {args.db}")
    print(f"Output directory: {out_dir}")
    print("Mode            : READ-ONLY audit; no DB/reference/queue changes")
    print()

    if not args.reference_dir.exists():
        print(f"ERROR: reference directory not found: {args.reference_dir}")
        return 2

    json_files, occurrences = read_reference_occurrences(args.reference_dir)
    if not occurrences:
        print("ERROR: no concept items found. Check the reference directory and JSON schema.")
        return 2

    print(f"Reference JSON files parsed: {len(json_files):,}")
    print(f"Concept occurrences         : {len(occurrences):,}")
    print(f"Unique concept IDs          : {len(set(x['concept_id'] for x in occurrences)):,}")

    vocab = lookup_vocab(args.db, [x["concept_id"] for x in occurrences])
    audited = []
    statuses = Counter()
    per_cohort = defaultdict(Counter)
    missing_ids = set()

    for occ in occurrences:
        dbrow = vocab.get(occ["concept_id"])
        status = primary_status(occ, dbrow)
        statuses[status] += 1
        per_cohort[occ["cohort_id"]][status] += 1
        if dbrow is None:
            missing_ids.add(occ["concept_id"])
        row = dict(occ)
        row["audit_status"] = status
        row["db_concept_name"] = (dbrow or {}).get("concept_name") or ""
        row["db_domain"] = (dbrow or {}).get("domain_id") or ""
        row["db_vocabulary_id"] = (dbrow or {}).get("vocabulary_id") or ""
        row["db_concept_class_id"] = (dbrow or {}).get("concept_class_id") or ""
        row["db_standard_concept"] = (dbrow or {}).get("standard_concept") or ""
        row["db_concept_code"] = (dbrow or {}).get("concept_code") or ""
        row["db_valid_start_date"] = (dbrow or {}).get("valid_start_date") or ""
        row["db_valid_end_date"] = (dbrow or {}).get("valid_end_date") or ""
        row["db_invalid_reason"] = (dbrow or {}).get("invalid_reason") or ""
        audited.append(row)

    occurrence_fields = [
        "cohort_id", "source_file", "codeset_id", "codeset_name", "item_index",
        "concept_id", "source_concept_name", "source_domain", "source_standard_concept",
        "include_descendants", "include_mapped", "is_excluded", "is_entry_codeset",
        "entry_arm_domains", "audit_status", "db_concept_name", "db_domain",
        "db_vocabulary_id", "db_concept_class_id", "db_standard_concept",
        "db_concept_code", "db_valid_start_date", "db_valid_end_date", "db_invalid_reason"
    ]
    csv_write(out_dir / "concept_occurrence_audit.csv", audited, occurrence_fields)

    unique_rows = []
    by_id = defaultdict(list)
    for row in audited:
        by_id[row["concept_id"]].append(row)
    for cid, rows in sorted(by_id.items()):
        first = rows[0]
        unique_rows.append({
            "concept_id": cid,
            "source_names": " | ".join(sorted(set(r["source_concept_name"] for r in rows if r["source_concept_name"]))),
            "source_domains": " | ".join(sorted(set(r["source_domain"] for r in rows if r["source_domain"]))),
            "db_concept_name": first["db_concept_name"],
            "db_domain": first["db_domain"],
            "db_vocabulary_id": first["db_vocabulary_id"],
            "db_standard_concept": first["db_standard_concept"],
            "db_valid_start_date": first["db_valid_start_date"],
            "db_valid_end_date": first["db_valid_end_date"],
            "db_invalid_reason": first["db_invalid_reason"],
            "audit_statuses": " | ".join(sorted(set(r["audit_status"] for r in rows))),
            "occurrence_count": len(rows),
            "cohort_count": len(set(r["cohort_id"] for r in rows)),
            "cohorts": ";".join(sorted(set(r["cohort_id"] for r in rows))),
        })
    csv_write(out_dir / "unique_concept_audit.csv", unique_rows, list(unique_rows[0].keys()))

    cohort_rows = []
    for cohort, counts in sorted(per_cohort.items(), key=lambda x: x[0]):
        cohort_rows.append({
            "cohort_id": cohort,
            "concept_occurrences": sum(counts.values()),
            "missing_occurrences": sum(v for k, v in counts.items() if k == "MISSING_FROM_CURRENT_VOCABULARY"),
            "invalid_occurrences": sum(v for k, v in counts.items() if "INVALID" in k),
            "nonstandard_occurrences": sum(v for k, v in counts.items() if "NOT_STANDARD" in k),
            "domain_mismatch_occurrences": sum(v for k, v in counts.items() if "DOMAIN_MISMATCH" in k),
            "entry_missing_occurrences": sum(1 for r in audited if r["cohort_id"] == cohort and r["is_entry_codeset"] and r["audit_status"] == "MISSING_FROM_CURRENT_VOCABULARY"),
            "statuses": json.dumps(dict(counts), sort_keys=True),
        })
    csv_write(out_dir / "cohort_audit_summary.csv", cohort_rows, list(cohort_rows[0].keys()))

    print("\n=== OCCURRENCE STATUS COUNTS ===")
    for status, count in statuses.most_common():
        print(f"{status:<52} {count:>8,}")
    print(f"{'Unique missing IDs':<52} {len(missing_ids):>8,}")
    print(f"{'Cohorts with missing concepts':<52} {sum(1 for r in cohort_rows if r['missing_occurrences']):>8,}")

    archive_scan_summary = []
    recovered = {}
    if args.scan_archives and missing_ids:
        roots = args.archive_root if args.archive_root else DEFAULT_ARCHIVE_ROOTS
        archives = find_zip_candidates(roots)
        print(f"\n=== OPTIONAL LOCAL ARCHIVE SCAN ===")
        print(f"ZIP candidates: {len(archives)}. This may take time for large archives.")
        for i, (archive, size) in enumerate(archives, 1):
            print(f"[{i}/{len(archives)}] {archive} ({size / 1e6:.1f} MB)")
            matches, result = scan_archive_for_ids(archive, missing_ids - set(recovered))
            archive_scan_summary.append({
                "archive": str(archive),
                "size_bytes": size,
                "result": result,
                "matched_missing_ids": len(matches),
                "matched_ids": ";".join(map(str, sorted(matches))),
            })
            for cid, row in matches.items():
                recovered.setdefault(cid, row)
            if len(recovered) == len(missing_ids):
                print("All missing IDs located in local archives; stopping scan.")
                break

        csv_write(out_dir / "archive_scan_summary.csv", archive_scan_summary,
                  ["archive", "size_bytes", "result", "matched_missing_ids", "matched_ids"])
        if recovered:
            cols = sorted(set(k for row in recovered.values() for k in row))
            rows = [recovered[cid] for cid in sorted(recovered)]
            csv_write(out_dir / "supplemental_concept_rows_for_review.csv", rows, cols)
        print(f"Missing IDs found in local ZIP archives: {len(recovered):,} / {len(missing_ids):,}")
        print("Note: recovered rows are evidence only; they are NOT merged into DuckDB.")
    elif args.scan_archives:
        print("\nNo missing concept IDs found in the references; archive scan skipped.")

    summary = {
        "created_at_local": datetime.now().isoformat(timespec="seconds"),
        "reference_dir": str(args.reference_dir),
        "db_path": str(args.db),
        "output_dir": str(out_dir),
        "reference_json_files": len(json_files),
        "concept_occurrences": len(occurrences),
        "unique_concept_ids": len(set(x["concept_id"] for x in occurrences)),
        "unique_missing_ids": len(missing_ids),
        "occurrence_status_counts": dict(statuses),
        "cohorts_with_missing_concepts": sum(1 for r in cohort_rows if r["missing_occurrences"]),
        "archive_scan_enabled": bool(args.scan_archives),
        "missing_ids_found_in_local_archives": len(recovered),
        "missing_ids_not_found_in_scanned_archives": sorted(missing_ids - set(recovered)),
        "safety": "No vocabulary DB, reference JSON, or benchmark queue was modified.",
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    remediation = f"""JBI VOCABULARY COMPATIBILITY AUDIT — REMEDIATION NOTES

Output: {out_dir}

Files:
- concept_occurrence_audit.csv: every source concept occurrence with vocabulary status
- unique_concept_audit.csv: one row per unique concept ID
- cohort_audit_summary.csv: counts by cohort
- summary.json: machine-readable summary
"""
    if args.scan_archives:
        remediation += """- archive_scan_summary.csv: local ZIPs inspected
- supplemental_concept_rows_for_review.csv: exact rows found in local ZIPs, if any

NEXT ACTION:
1. Review missing IDs and their source names in unique_concept_audit.csv.
2. If archive scan found exact rows, verify each row's vocabulary version and provenance.
3. If IDs remain missing, obtain a vocabulary package compatible with the source cohort definitions.
4. Keep missing, invalid, non-standard, and domain-mismatched concepts explicitly audited.
5. Only after source validation, create a separate versioned vocabulary DB/reference build.
6. Rerun unit tests and reference-quality gates before any benchmark run.

Do not guess replacement IDs, silently drop missing concepts, or change the frozen queue.
"""
    else:
        remediation += """NEXT ACTION:
1. Review missing IDs and their source names in unique_concept_audit.csv.
2. To search local ZIPs for exact missing concept records, rerun with --scan-archives.
3. If IDs remain missing, obtain a vocabulary package compatible with the source cohort definitions.
4. Only after source validation, create a separate versioned vocabulary DB/reference build.

Do not guess replacement IDs, silently drop missing concepts, or change the frozen queue.
"""
    (out_dir / "REMEDIATION.txt").write_text(remediation, encoding="utf-8")
    print(f"\n=== OUTPUTS ===")
    print(f"Occurrence audit : {out_dir / 'concept_occurrence_audit.csv'}")
    print(f"Unique IDs       : {out_dir / 'unique_concept_audit.csv'}")
    print(f"Cohort summary   : {out_dir / 'cohort_audit_summary.csv'}")
    print(f"JSON summary     : {out_dir / 'summary.json'}")
    print(f"Remediation plan : {out_dir / 'REMEDIATION.txt'}")
    print("\nFinished. No source database, reference JSON, or benchmark queue was changed.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
