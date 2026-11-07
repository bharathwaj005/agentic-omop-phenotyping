#!/usr/bin/env python3
"""Inter-rater agreement (Cohen's kappa) for docs/review/review_sheet.csv.

    python scripts/review_agreement.py docs/review/review_sheet.csv
"""
import sys
from collections import Counter

import pandas as pd


def cohen_kappa(a, b):
    n = len(a)
    if n == 0:
        return None
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def main(path):
    df = pd.read_csv(path, dtype=str).fillna("")
    done = df[(df.rater_1.str.strip() != "") & (df.rater_2.str.strip() != "")]
    print(f"rows rated by both raters: {len(done)} of {len(df)}")
    for side, g in [("ALL", done)] + list(done.groupby("side")):
        k = cohen_kappa(list(g.rater_1.str.upper()), list(g.rater_2.str.upper()))
        print(f"  {side:15} n={len(g):4}  kappa={'NA' if k is None else f'{k:.3f}'}")
    pred = done[done.side.isin(["MATCHED", "PREDICTED_ONLY"])]
    if len(pred):
        agree_ok = ((pred.rater_1.str.upper() == "A") & (pred.rater_2.str.upper() == "A")).mean()
        print(f"  predicted concepts judged appropriate by both raters: {agree_ok:.1%}")
    missed = done[done.side == "MISSED"]
    if len(missed):
        ess = ((missed.rater_1.str.upper() == "E") & (missed.rater_2.str.upper() == "E")).mean()
        print(f"  missed concepts judged essential by both raters: {ess:.1%}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "docs/review/review_sheet.csv")
