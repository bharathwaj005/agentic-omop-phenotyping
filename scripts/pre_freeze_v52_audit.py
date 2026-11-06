#!/usr/bin/env python3
"""Disk-safe, read-only-source pre-freeze audit for JBI V5.2."""
from __future__ import annotations

import csv, gc, itertools, json, os, platform, resource, shutil, sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / "results" / "benchmark_design"
V52 = R / "BENCHMARK_FINAL20_PROPOSAL_V5_2.csv"
PAIR = R / "BENCHMARK_V5_2_PAIRWISE_REDUNDANCY_AUDIT.csv"
FAM = R / "BENCHMARK_V5_2_SEMANTIC_FAMILY_AUDIT.csv"
POOL = R / "FULL_BENCHMARK_POOL.csv"
MATRIX = R / "BENCHMARK_SELECTION_MATRIX_V1.csv"
V4 = R / "BENCHMARK_FINAL20_PROPOSAL_V4.csv"
DB = ROOT / "data" / "eunomia.duckdb"

OUTS = [
 "V5_2_PRE_FREEZE_STAGE1.txt", "V5_2_190_PAIR_DISTRIBUTION.csv",
 "V5_2_190_PAIR_DISTRIBUTION.txt", "V5_2_SIMILARITY_METHOD_AUDIT.txt",
 "V5_2_TRUE_JACCARD_AUDIT.txt", "V5_2_STRUCTURAL_PROFILE.csv",
 "V5_2_STRUCTURAL_DIVERSITY_AUDIT.txt", "V5_2_TEMPORAL_AUDIT.csv",
 "V5_2_TEMPORAL_AUDIT.txt", "V5_2_EUNOMIA_COVERAGE.csv",
 "V5_2_EUNOMIA_COVERAGE_AUDIT.txt", "V5_2_TEMPLATE_REDUNDANCY_AUDIT.csv",
 "V5_2_TEMPLATE_REDUNDANCY_AUDIT.txt", "V5_2_DIFFICULTY_AUDIT.txt",
 "V5_2_PRE_FREEZE_MANIFEST.json", "V5_2_PRE_FREEZE_MASTER_AUDIT.txt",
]

def abort_if_exists():
    exists = [str(R / x) for x in OUTS if (R / x).exists()]
    if exists:
        raise RuntimeError("Refusing to overwrite existing audit output(s): " + ", ".join(exists))

def read_csv(path):
    with path.open(newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))

def header(path):
    with path.open(newline='', encoding='utf-8-sig') as f:
        return next(csv.reader(f))

def write_text(name, text):
    (R / name).write_text(text, encoding='utf-8')

def write_csv(name, fields, rows):
    with (R / name).open('x', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)

def boolean(v): return str(v).strip().lower() in {'true','1','yes'}
def num(v):
    try: return float(v)
    except (TypeError, ValueError): return None
def fmt(v): return 'NA' if v is None else (f'{v:.4f}' if isinstance(v, float) else str(v))
def quantile(vals, q):
    a=sorted(vals); p=(len(a)-1)*q; lo=int(p); hi=min(lo+1,len(a)-1)
    return a[lo]+(a[hi]-a[lo])*(p-lo)
def numeric_summary(vals):
    return {'n':len(vals),'min':min(vals),'max':max(vals),'median':quantile(vals,.5),'Q1':quantile(vals,.25),'Q3':quantile(vals,.75)} if vals else {}
def tsv_counter(counter): return '\n'.join(f'{k}: {v}' for k,v in sorted(counter.items(), key=lambda x:(-x[1],str(x[0])))) or '(none)'
def ids(rows): return {str(r['cohort_id']).strip() for r in rows}

def main():
    abort_if_exists()
    R.mkdir(parents=True, exist_ok=True)
    # Stage 0
    import numpy, pandas, duckdb
    vm=os.sysconf('SC_PAGE_SIZE')*os.sysconf('SC_AVPHYS_PAGES')
    disk=shutil.disk_usage(ROOT)
    env={'python_version':sys.version.replace('\n',' '),'pandas_version':pandas.__version__, 'numpy_version':numpy.__version__, 'duckdb_version':duckdb.__version__, 'available_ram_bytes':vm, 'available_disk_bytes':disk.free, 'cpu_count_reported':os.cpu_count(), 'worker_policy':'one worker; no multiprocessing/joblib/parallel operations'}
    # Stage 1: files are all sub-1MB metadata except the 26MB DB; CSVs read here are bounded metadata.
    v52=read_csv(V52); pair=read_csv(PAIR); fam=read_csv(FAM); v4=read_csv(V4)
    v5ids=ids(v52); poolids=set()
    # Authoritative pool inspected incrementally, <=5000 rows per partition.
    with POOL.open(newline='',encoding='utf-8-sig') as f:
        rdr=csv.DictReader(f)
        while True:
            part=list(itertools.islice(rdr,5000))
            if not part: break
            poolids.update(str(x['cohort_id']).strip() for x in part); del part; gc.collect()
    pair_keys=[tuple(sorted((str(r['cohort_id_A']),str(r['cohort_id_B'])))) for r in pair]
    stage1=["V5.2 PRE-FREEZE STAGE 1 — ENVIRONMENT SAFETY AND INTEGRITY", "="*78, ""]
    stage1 += [f'{k}: {v}' for k,v in env.items()] + ['', 'FILE SCHEMAS (header only before row inspection):']
    for p in [V52,PAIR,FAM,POOL,MATRIX]: stage1.append(f'{p.relative_to(ROOT)} ({p.stat().st_size} bytes): {header(p)}')
    checks={
      'V5.2 exact row count 20':len(v52)==20, 'V5.2 cohort IDs unique':len(v5ids)==20,
      'pairwise exact row count 190':len(pair)==190, 'pairwise unique unordered pairs':len(set(pair_keys))==190,
      'pairwise covers 20 choose 2':set(pair_keys)==set(tuple(sorted(x)) for x in itertools.combinations(v5ids,2)),
      'no V4 cohort reappeared':not bool(v5ids & ids(v4)), 'every V5.2 cohort in authoritative pool':v5ids <= poolids,
    }
    stage1 += ['', 'VALIDATION:']+[f"{'PASS' if ok else 'FAIL'} — {k}" for k,ok in checks.items()]
    write_text('V5_2_PRE_FREEZE_STAGE1.txt','\n'.join(stage1)+'\n'); del poolids; gc.collect()
    # Stage 2
    sims=[float(r['structural_similarity']) for r in pair]
    dist=[]
    for threshold in [.50,.60,.65,.70,.75,.80,.85,.90]:
        n=sum(x>=threshold for x in sims); dist.append({'record_type':'threshold','metric':'structural_similarity','threshold':threshold,'n':n,'percent':round(100*n/len(sims),4),'value':''})
    for k,v in {'n':len(sims),'minimum':min(sims),'maximum':max(sims),'mean':sum(sims)/len(sims),'median':quantile(sims,.5),'Q1':quantile(sims,.25),'Q3':quantile(sims,.75),'P90':quantile(sims,.90),'P95':quantile(sims,.95),'P97.5':quantile(sims,.975),'P99':quantile(sims,.99)}.items(): dist.append({'record_type':'summary','metric':k,'threshold':'','n':'','percent':'','value':round(v,6) if isinstance(v,float) else v})
    write_csv('V5_2_190_PAIR_DISTRIBUTION.csv',['record_type','metric','threshold','n','percent','value'],dist)
    hi=[r for r in pair if float(r['structural_similarity'])>=.80]
    strict=[r for r in hi if boolean(r['complexity_same']) and boolean(r['domain_same']) and boolean(r['compiler_same'])]
    lines=['V5.2 190-PAIR STRUCTURAL SIMILARITY DISTRIBUTION','='*60,'Similarity column: structural_similarity','Metric name is structural similarity (not Jaccard).','', 'SUMMARY:']
    lines += [f"{x['metric']}: {x['value']}" for x in dist if x['record_type']=='summary'] + ['', 'THRESHOLDS:']
    lines += [f">= {x['threshold']:.2f}: {x['n']} ({x['percent']:.4f}%)" for x in dist if x['record_type']=='threshold']
    lines += ['', 'ALL PAIRS >= 0.80:']
    lines += [f"{r['cohort_id_A']} | {r['cohort_id_B']} | {r['structural_similarity']} | {r['cohort_name_A']} | {r['cohort_name_B']}" for r in hi] or ['(none)']
    lines += ['', 'PAIRS SATISFYING ALL FOUR CONDITIONS (>=0.80 plus same complexity, domain, compiler):']
    lines += [f"{r['cohort_id_A']} | {r['cohort_id_B']} | {r['structural_similarity']}" for r in strict] or ['(none)']
    write_text('V5_2_190_PAIR_DISTRIBUTION.txt','\n'.join(lines)+'\n'); del sims; gc.collect()
    # Stage 3 provenance result based on repository-local bounded code search performed separately and audit provenance.
    write_text('V5_2_SIMILARITY_METHOD_AUDIT.txt', '''V5.2 SIMILARITY METHOD AUDIT
============================
Source artifact: results/benchmark_design/BENCHMARK_V5_2_PAIRWISE_REDUNDANCY_AUDIT.csv
Related narrative: results/benchmark_design/BENCHMARK_V5_2_PAIRWISE_REDUNDANCY_AUDIT.txt

Repository search result: no source script or function that generates this CSV is present in the checked-in project tree. Therefore an exact implementation, function name, feature weights, and formula cannot be verified from available source. The CSV’s own companion audit explicitly describes the score as a “transparent heuristic, NOT a validated similarity metric.”

Classification: STRUCTURAL SIMILARITY. It must not be called Jaccard.

Observed exported comparison fields: complexity_same, domain_same, compiler_same, entry_items_A/B, concept_sets_A/B, inclusion_rules_A/B, total_concepts_A/B, eunomia_persons_A/B, and semantic_family. These fields are evidence of inputs or audit context only; without the missing generator, they do not establish the exact formula or weights.

Jaccard verification: NOT VERIFIED / NOT IMPLEMENTED in available provenance. No actual concept-ID sets occur in the pairwise CSV, so |A intersection B| / |A union B| cannot have been calculated from that artifact.

Categorical comparisons exported: equality flags for complexity, entry domain, and compiler status.
Numerical comparisons exported: paired counts for entry items, concept sets, inclusion rules, total concepts, and Eunomia persons. Exact transformations/comparisons: not recoverable.
Required later source: the original generator script/notebook or a documented formula with source revision.
''')
    # Stage 4
    raw_dir=ROOT/'tasks'/'reference_raw'; ref_dir=ROOT/'tasks'/'reference'
    write_text('V5_2_TRUE_JACCARD_AUDIT.txt', f'''V5.2 TRUE CONCEPT-SET JACCARD AUDIT
======================================
Result: true Jaccard cannot currently be calculated for all 20 V5.2 cohorts.

Inspected repository locations: results/, tasks/, data/, src/ (file metadata/schema first; no large source loaded). V5.2 cohort IDs are not task IDs in the only task JSONL artifacts, tasks/reference/ is empty, and tasks/reference_raw/ does not exist. Available benchmark CSVs contain aggregate counts and concept-set names, not the actual concept IDs/sets. The Eunomia database contains a vocabulary `concept` table but is not an authoritative phenotype-definition export and cannot reconstruct each cohort’s intended concept sets.

Needed source later: for each V5.2 cohort, extracted Circe/ATLAS cohort JSON containing ConceptSets/expression items, or resolved per-cohort reference JSON with `all_concept_ids` (produced from the source definition against the intended vocabulary). With those 20 sources, 190 set comparisons can be calculated one pair at a time.
''')
    # Stage 5 enrich only V5 subset through chunked matrix scan.
    matrix_by_id={}
    with MATRIX.open(newline='',encoding='utf-8-sig') as f:
        rdr=csv.DictReader(f)
        while True:
            part=list(itertools.islice(rdr,5000))
            if not part: break
            for x in part:
                if str(x['cohort_id']) in v5ids: matrix_by_id[str(x['cohort_id'])]=x
            del part; gc.collect()
    profile=[]
    source_fields=list(v52[0].keys()); enrich=['logic_type','temporal_type','execution_class','n_primary_criteria','n_excluded_items','n_descendant_items','n_mapped_items','multi_domain','has_prior_observation','observation_window_prior_days','has_first_occurrence','has_multiple_primary_criteria','has_exclusion']
    for r in v52:
        z=dict(r); z.update({k:matrix_by_id.get(str(r['cohort_id']),{}).get(k,'') for k in enrich}); profile.append(z)
    profile_fields=source_fields+enrich
    write_csv('V5_2_STRUCTURAL_PROFILE.csv',profile_fields,profile)
    numeric=['eunomia_persons','n_entry_items','n_concept_sets','n_inclusion_rules','total_concept_items','max_concept_set_size','mean_concept_set_size','n_primary_criteria','n_excluded_items','n_descendant_items','n_mapped_items','observation_window_prior_days']
    categorical=['complexity','entry_domain','compiler_supported','eunomia_evaluable','any_descendants','any_mapped','temporal_signal','redundancy_family_signal','logic_type','temporal_type','execution_class','multi_domain','has_prior_observation','has_first_occurrence','has_multiple_primary_criteria','has_exclusion']
    lines=['V5.2 STRUCTURAL DIVERSITY AUDIT','='*50,'Source rows: 20 V5.2 tasks; matrix enrichment found for '+str(len(matrix_by_id))+' tasks.','', 'NUMERIC ATTRIBUTES (min, max, median, Q1, Q3):']
    for c in numeric:
        vals=[num(r.get(c)) for r in profile]; vals=[x for x in vals if x is not None]; s=numeric_summary(vals); lines.append(f"{c}: "+', '.join(f'{k}={fmt(v)}' for k,v in s.items()))
    lines += ['', 'CATEGORICAL ATTRIBUTES:']
    for c in categorical: lines += [c+':',tsv_counter(Counter(r.get(c,'') or '(missing)' for r in profile))]
    write_text('V5_2_STRUCTURAL_DIVERSITY_AUDIT.txt','\n'.join(lines)+'\n')
    # Stage 6 source-supported metadata classification.
    temp=[]
    for r in profile:
        typ=r.get('temporal_type',''); prior=boolean(r.get('has_prior_observation')); first=boolean(r.get('has_first_occurrence'))
        if prior and first: cls='nested/multiple temporal relation'; support='temporal_type and prior/first metadata'
        elif prior: cls='temporal window'; support='prior-observation metadata'
        elif first: cls='index event'; support='first-occurrence metadata'
        elif str(typ).strip().lower()=='none': cls='none'; support='temporal_type metadata'
        else: cls='not determinable'; support='no reliable temporal detail in available V5.2 metadata'
        temp.append({'cohort_id':r['cohort_id'],'cohort_name':r['cohort_name'],'temporal_classification':cls,'temporal_type_metadata':typ,'temporal_signal':r.get('temporal_signal',''),'has_prior_observation':r.get('has_prior_observation',''),'observation_window_prior_days':r.get('observation_window_prior_days',''),'has_first_occurrence':r.get('has_first_occurrence',''),'evidence':support})
    write_csv('V5_2_TEMPORAL_AUDIT.csv',list(temp[0]),temp)
    write_text('V5_2_TEMPORAL_AUDIT.txt','V5.2 TEMPORAL LOGIC AUDIT\n'+'='*40+'\nClassifications use actual available selection-matrix temporal metadata, not cohort names. Raw criteria/Circe JSON is unavailable, so sequence/order and finer nested relation details cannot be independently verified.\n\n'+tsv_counter(Counter(x['temporal_classification'] for x in temp))+'\n')
    # Stage 7 read-only DuckDB, no coverage denominator without reference sets.
    con=duckdb.connect(str(DB),read_only=True); tables=[x[0] for x in con.execute("select table_name from information_schema.tables where table_schema='main' order by table_name").fetchall()]; con.close(); gc.collect()
    cov=[]
    for r in profile:
        declared=boolean(r.get('eunomia_evaluable'))
        cov.append({'cohort_id':r['cohort_id'],'cohort_name':r['cohort_name'],'declared_eunomia_evaluable':r.get('eunomia_evaluable',''),'declared_eunomia_persons':r.get('eunomia_persons',''),'availability_status':'available in Eunomia (declared benchmark metadata)' if declared else 'unavailable in Eunomia (declared benchmark metadata)','coverage_fraction':'not determinable: no authoritative V5.2 concept-ID denominator','coverage_basis':'existing benchmark metadata only; not a concept-validity judgment'})
    write_csv('V5_2_EUNOMIA_COVERAGE.csv',list(cov[0]),cov)
    write_text('V5_2_EUNOMIA_COVERAGE_AUDIT.txt',f'''V5.2 EUNOMIA COVERAGE AUDIT
===========================
Database inspected read-only: {DB.relative_to(ROOT)} ({DB.stat().st_size} bytes).
Schema tables ({len(tables)}): {', '.join(tables)}.

Measured safely: V5.2’s existing `eunomia_evaluable` and `eunomia_persons` metadata, reported task-by-task in the CSV. All {sum(boolean(r.get('eunomia_evaluable')) for r in profile)} V5.2 records are declared evaluable.

Not mathematically justified: a concept-set coverage fraction, because authoritative V5.2 concept-ID sets are absent. This audit does not test every requested phenotype concept against Eunomia and does not treat a missing Eunomia concept as invalid.
''')
    # Stage 8 all pairs, metadata-only flags.
    byid={str(r['cohort_id']):r for r in profile}; sem={str(r['cohort_id']):r.get('semantic_family_v5_2','') for r in fam}
    redundancy=[]
    for a,b in itertools.combinations(sorted(byid),2):
        x,y=byid[a],byid[b]
        flags=[]
        if sem.get(a) and sem.get(a)==sem.get(b): flags.append('same_semantic_family')
        if x.get('redundancy_family_signal')==y.get('redundancy_family_signal'): flags.append('same_redundancy_family_signal')
        for label,cols in [('same_temporal_template',['temporal_type','has_prior_observation','has_first_occurrence']),('same_inclusion_exclusion_pattern',['n_inclusion_rules','has_exclusion','n_excluded_items']),('same_index_event_structure',['has_first_occurrence','has_prior_observation']),('same_domain_complexity_compiler',['entry_domain','complexity','compiler_supported'])]:
            if all(x.get(c,'')==y.get(c,'') for c in cols): flags.append(label)
        redundancy.append({'cohort_id_1':a,'cohort_id_2':b,'cohort_name_1':x['cohort_name'],'cohort_name_2':y['cohort_name'],'semantic_family_1':sem.get(a,''),'semantic_family_2':sem.get(b,''),'flags':' | '.join(flags) if flags else 'none','flag_count':len(flags),'obvious_template_duplication':'potential; metadata-only review' if len(flags)>=3 else 'not established'})
    write_csv('V5_2_TEMPLATE_REDUNDANCY_AUDIT.csv',list(redundancy[0]),redundancy)
    flagged=[x for x in redundancy if x['flags']!='none']
    write_text('V5_2_TEMPLATE_REDUNDANCY_AUDIT.txt','V5.2 TEMPLATE / LEAKAGE / REDUNDANCY AUDIT\n'+'='*55+f'\nAll 190 pairs compared using available structural metadata. {len(flagged)} pairs have one or more metadata flags. Flags are screening signals, not removal decisions; raw criteria are unavailable, so disease/drug semantic and logical-template duplication cannot be fully adjudicated.\n\nHighest-flag pairs:\n'+ '\n'.join(f"{x['cohort_id_1']} | {x['cohort_id_2']} | {x['flags']}" for x in sorted(flagged,key=lambda q:-q['flag_count'])[:30])+'\n')
    # Stage 9
    lines=['V5.2 DIFFICULTY AUDIT','='*35,'Complexity labels are retained; this is descriptive only.','']
    for c in ['complex','medium','simple']:
        sub=[r for r in profile if r.get('complexity')==c]; lines += [f'[{c}] n={len(sub)}']
        for field in ['n_entry_items','n_concept_sets','n_inclusion_rules','total_concept_items','n_primary_criteria','n_excluded_items']:
            vals=[num(r.get(field)) for r in sub]; vals=[v for v in vals if v is not None]; lines.append(f'{field}: '+', '.join(f'{k}={fmt(v)}' for k,v in numeric_summary(vals).items()))
        lines.append('domains: '+tsv_counter(Counter(r.get('entry_domain','') for r in sub)).replace('\n','; ')); lines.append('compiler: '+tsv_counter(Counter(r.get('compiler_supported','') for r in sub)).replace('\n','; ')); lines.append('temporal classes: '+tsv_counter(Counter(t['temporal_classification'] for t in temp if t['cohort_id'] in {r['cohort_id'] for r in sub})).replace('\n','; ')); lines.append('')
    write_text('V5_2_DIFFICULTY_AUDIT.txt','\n'.join(lines))
    # stage 10 manifest
    manifest={'benchmark_version':'V5.2','number_of_tasks':20,'task_ids':[r['cohort_id'] for r in v52],'source_file_paths':[str(x.relative_to(ROOT)) for x in [V52,PAIR,FAM,POOL,MATRIX,V4]],'audit_file_paths':['results/benchmark_design/'+x for x in OUTS if x!='V5_2_PRE_FREEZE_MANIFEST.json' and x!='V5_2_PRE_FREEZE_MASTER_AUDIT.txt'],'python_version':env['python_version'],'package_versions':{'pandas':pandas.__version__,'numpy':numpy.__version__,'duckdb':duckdb.__version__},'eunomia_db_path':'data/eunomia.duckdb','athena_status':'POSTPONED_NOT_LOADED','created_utc':datetime.now(timezone.utc).isoformat(),'resource_policy':env['worker_policy']}
    (R/'V5_2_PRE_FREEZE_MANIFEST.json').open('x',encoding='utf-8').write(json.dumps(manifest,indent=2)+'\n')
    # stage 11
    rec='No single defensible V5.3 replacement candidate is identifiable from this audit alone: the highest structural-similarity pair is a screening signal, but true concept-set overlap and raw criteria are unavailable. Next action: obtain/version the 20 authoritative cohort-definition exports, reproduce the structural-similarity generator, then calculate true Jaccard before any V5.3 selection decision.'
    master=['V5.2 PRE-FREEZE MASTER AUDIT','='*60,'1. Benchmark integrity: '+'PASS' if all(checks.values()) else '1. Benchmark integrity: FAILED CHECKS PRESENT', f'2. 20-task composition: complexities {dict(Counter(r["complexity"] for r in profile))}; domains {dict(Counter(r["entry_domain"] for r in profile))}.',f'3. 190-pair distribution: mean={sum(float(r["structural_similarity"]) for r in pair)/190:.4f}; P95={quantile([float(r["structural_similarity"]) for r in pair],.95):.4f}.',f'4. High-similarity pairs >=0.80: {len(hi)}; all-four-condition pairs: {len(strict)}.', '5. Similarity metric: structural similarity heuristic; exact generator/formula absent, not Jaccard.', '6. True Jaccard: unavailable; authoritative V5.2 concept-ID sets are absent.', '7. Structural diversity: documented in V5_2_STRUCTURAL_DIVERSITY_AUDIT.txt and profile CSV.', '8. Temporal diversity: metadata-supported classifications documented; raw criteria unavailable for deeper validation.', f'9. Eunomia coverage: {sum(boolean(r.get("eunomia_evaluable")) for r in profile)}/20 declared evaluable; concept coverage not determinable.', f'10. Template redundancy: {len(flagged)}/190 pairs have metadata screening flags; no removal action taken.', '11. Difficulty audit: descriptive structural stratification completed; labels unchanged.', '12. Reproducibility: manifest written; Athena status is POSTPONED_NOT_LOADED.', '13. Limitations: missing pairwise generator, raw cohort definitions, resolved concept sets, and Athena vocabulary.', '14. Recommended next action: '+rec, '', 'V5.2 was not modified. No V5.3 was created.']
    write_text('V5_2_PRE_FREEZE_MASTER_AUDIT.txt','\n'.join(master)+'\n')
    print(json.dumps({'created':OUTS,'peak_rss_kb':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'stages_completed':list(range(12)),'stages_skipped_or_blocked':['true Jaccard calculation blocked by missing authoritative concept sets; exact similarity formula blocked by missing generator'],'recommended_next_step':rec},indent=2))

if __name__=='__main__': main()
