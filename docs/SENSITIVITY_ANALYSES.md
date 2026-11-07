# Sensitivity analyses (post hoc, 7 Nov 2026)

## Why

The runner retries a failed run only when its error matches a pre-specified infrastructure list (`_classify_infrastructure` in `scripts/run_benchmark.py`: connection refused/reset, unreachable host, DNS failure, HTTP 5xx, "process killed"). Errors reading "RemoteDisconnected: Remote end closed connection without response" are not on the list. On an 8 GB laptop this error is what the client sees when the operating system's out-of-memory (OOM) killer terminates the Ollama server mid-response.

## V5.3 track (submitted paper)

In the official runs, T05, T11 and T17 were stopped by the memory preflight and re-executed once (paper, Methods). The retries of T05 C1, T11 C3 and T17 C2 ended with RemoteDisconnected and are counted as failures. The system journal shows OOM-kill entries for the Ollama service within ±5 minutes of the T11 C3 (27 Oct 23:31) and T17 C2 (28 Oct 01:47) failures, and none for T05 C1 (27 Oct 19:56).

The three cells were re-executed a second time under the official freeze manifest, each in its own folder (`results/codex_20261025/runs/sensitivity_v53_*`):

| Cell | Official | Second re-execution |
| --- | --- | --- |
| T05 C1 | failed (RemoteDisconnected) | success, F1 = 0.2590 |
| T11 C3 | failed (RemoteDisconnected) | success, F1 = 0.0029 |
| T17 C2 | failed (RemoteDisconnected) | timed out (1,200 s) |

| Config | Scored (official → sensitivity) | Mean F1 scored | Mean F1 All=0 |
| --- | --- | --- | --- |
| C1 | 11 → 12 / 20 | 0.2477 → 0.2486 | 0.1362 → 0.1492 |
| C2 | 14 → 14 / 20 | 0.2215 → 0.2215 | 0.1550 → 0.1550 |
| C3 | 15 → 16 / 20 | 0.1998 → 0.1875 | 0.1498 → 0.1500 |
| C4 | 16 → 16 / 20 | 0.1517 → 0.1517 | 0.1213 → 0.1213 |

Paired Wilcoxon over tasks scored by both configurations (the paper's method; the official p-values are reproduced exactly): C1 vs C2 p = 0.8438 → 0.8438; C1 vs C3 0.2500 → 0.2500; C1 vs C4 0.1250 → 0.0625. Holm-adjusted p ≥ 0.19. **Conclusions unchanged:** no significant V5.3 difference; C2 remains most dependable under All=0. This analysis is reported in Section 4.1.2 of the manuscript.

## ADN extension track

A08 C2 failed with RemoteDisconnected at 16:10 on 7 Nov 2026; the journal shows the Ollama service OOM-killed at 16:10:48. A sensitivity re-run is reported in `docs/AD_NEUROINFLAMMATION_TRACK.md`.

## Protocol amendment for future runs (not applied retroactively)

Before any new benchmark run, add `"remote end closed connection" in text or "remotedisconnected" in text` to `_classify_infrastructure`, and record the change (with its date) in a new freeze manifest. The submitted results and the ADN primary analysis keep the original rule.
