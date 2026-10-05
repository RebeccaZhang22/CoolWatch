# Probe classification audit

Bank: `sha256:755d80995f007185218237bf861e3c9982fae197849ba2b614eccad209b9823e`

Scores measure detector classification, not generated-answer leakage or tool execution success. Null labels are scored but excluded from classification metrics.

| Risk | Cases | TP | FN | FP | TN | Unlabeled | Errors |
|---|---:|---:|---:|---:|---:|---:|---:|
| harmful | 2 | 0 | 0 | 0 | 2 | 0 | 0 |
| prompt_leakage | 10 | 5 | 1 | 0 | 4 | 0 | 0 |
| ipi | 2 | 1 | 1 | 0 | 0 | 0 | 0 |
