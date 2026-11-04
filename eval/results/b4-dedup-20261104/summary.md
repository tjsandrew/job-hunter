# B4 duplicate removal: accuracy (threshold 0.6)

| Set | Pairs | Duplicates | Precision | Recall | F1 | TP / FP / FN / TN |
|---|---|---|---|---|---|---|
| Staging pulls (real, labelled) | 73 | 11 | 1.00 | 0.36 | 0.53 | 4 / 0 / 7 / 62 |
| Synthetic fixture (tuning set) | 16 | 8 | 1.00 | 1.00 | 1.00 | 8 / 0 / 0 / 8 |

Staging set: 11 duplicates, 62 hard non-duplicates; 1 unsure pair left out.

Missed duplicates:

| Pair | A | B | Why missed | Description similarity |
|---|---|---|---|---|
| 7 | adzuna: Evolution Singapore | Data & Integration Engineer, AI (Banking, 1-year renewable contract) | mycareersfuture: EVOLUTION RECRUITMENT SOLUTIONS PTE. LTD. | Data & Integration Engineer, AI (Banking, 1-year renewable contract) | employer/title key differs | 0.83 |
| 10 | adzuna: AVENSYS CONSULTING PTE. LTD. | Senior Data Engineer - Azure & Databricks (Banking) | mycareersfuture: AVENSYS CONSULTING PTE. LTD. | Senior Data Engineer -Azure / Databricks Platform (Corporate Banking) | employer/title key differs | 0.68 |
| 21 | adzuna: Aumni | Software Engineer III, Electronic Colo Trading | mycareersfuture: JPMORGAN CHASE BANK, N.A. | Software Engineer III, Electronic Colo Trading | employer/title key differs | 0.85 |
| 28 | adzuna: IG Group | Marketing Data Engineer, APAC | mycareersfuture: IG ASIA PTE. LTD. | Marketing Data Engineer, APAC | employer/title key differs | 0.79 |
| 78 | adzuna: DADACONSULTANTS PTE. LTD. | GPU/HPC Data Center Network Engineer (Low Latency) | mycareersfuture: DADACONSULTANTS PTE. LTD. | Network Engineer (GPU / HPC / Data Center Networks) | employer/title key differs | 0.75 |
| 79 | mycareersfuture: IG ASIA PTE. LTD. | Marketing Data Engineer, APAC | adzuna: ig | APAC Marketing Data Engineer — ETL Pipelines & Attribution | employer/title key differs | 0.73 |
| 80 | adzuna: Google LLC | Customer Engineer, High Performance Computing (English) | mycareersfuture: GOOGLE ASIA PACIFIC PTE. LTD. | Customer Engineer, High Performance Computing, Google Cloud - Singapore | employer/title key differs | 0.84 |

False merges: 0.

Threshold sweep on the staging set:

| Threshold | Precision | Recall | F1 |
|---|---|---|---|
| 0.3 | 1.00 | 0.36 | 0.53 |
| 0.4 | 1.00 | 0.36 | 0.53 |
| 0.5 | 1.00 | 0.36 | 0.53 |
| 0.6 | 1.00 | 0.36 | 0.53 |
| 0.7 | 1.00 | 0.36 | 0.53 |
| 0.8 | 1.00 | 0.36 | 0.53 |

What-if rules on the staging set (not in production; P / R / F1):

| Threshold | Text similarity only | Same employer head word + text |
|---|---|---|
| 0.3 | 0.17 / 1.00 / 0.29 | 0.31 / 0.91 / 0.47 |
| 0.4 | 0.21 / 1.00 / 0.35 | 0.48 / 0.91 / 0.62 |
| 0.5 | 0.28 / 1.00 / 0.44 | 0.62 / 0.91 / 0.74 |
| 0.6 | 0.34 / 1.00 / 0.51 | 0.67 / 0.91 / 0.77 |
| 0.7 | 0.50 / 0.91 / 0.65 | 0.64 / 0.82 / 0.72 |
| 0.8 | 0.64 / 0.64 / 0.64 | 0.67 / 0.55 / 0.60 |

Same-source reposts: 10 pairs, all identical text; merged 0 (by design two rows of one source never merge).
