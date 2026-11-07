# Clinician review sheet

Each row is one concept from a scored run. Two raters fill `rater_1` and `rater_2` independently:

- `MATCHED` / `PREDICTED_ONLY`: **A** = clinically appropriate for the phenotype, **I** = inappropriate, **U** = unsure
- `MISSED`: **E** = essential omission, **M** = minor omission, **U** = unsure

Then run `python scripts/review_agreement.py docs/review/review_sheet.csv` for Cohen's kappa.
Use only the generated concept sets; do not share patient data in this sheet.
