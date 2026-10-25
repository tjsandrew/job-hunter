# 13 - Pricing and plans (proposal)

Status: **proposal, 25 Oct 2026.** Billing is not built; the Upgrade button in the UI is a demo. The price below is a modelled number for the report, not a measured or market-tested one.

## 1. The plans

| | Free | Premium (proposed) |
|---|---|---|
| Price | S$0 | **S$6.90 / month** or **S$59 / year** (about S$4.92 / month) |
| AI uses per month | 5 | 50 |
| What counts as a use | One job per calendar month (Singapore time). A fit check, "Tailor with AI" and a cover letter written for the same job count **once**, and repeating any of them for that job is free | same |
| Always free, no limit | Rule-based tailoring (reorders bullets), resume builder, PDF export, tracker, Discover | same |

The limits already exist in code: `preparation/allowance.py` (`LIMITS = {"free": 5, "premium": 50}`, table `ai_tailor_uses`). Only the payment and the plan switch are missing.

## 2. Cost model

**Variable cost: the AI calls.** Only the AI features cost money per use; everything else is a database read or write.

| Item | Value | Source / status |
|---|---|---|
| One fit analysis on the school gateway (`gemma4:26b`) | about US$0.0008, 28-39 s | `docs/design/12-FIT-ANALYSIS.md`, benchmark of 4 postings and 1 demo profile; an estimate from tokens, **not** from a price page |
| Tailor with AI, cover letter | not measured | assumed to cost about the same as a fit analysis |
| Free user at the limit (5 uses) | about US$0.004 / month | 5 x 0.0008 |
| Premium user at the limit (50 uses) | about US$0.04 / month | 50 x 0.0008 |
| Same, if a commercial model cost 50 times more | about US$2 / month | sensitivity only |

The school gateway is a course resource, not a commercial service. If the product left the course, the model price would have to be re-measured; the sensitivity row shows the plan would still be above cost.

**Fixed cost: the platform.** Dominated by Aurora Serverless v2 (`docs/deployment/README.md`: US$0.20 per ACU-hour, US$0.11 per GB-month, 0-1 ACU, auto-pause after 30 idle minutes).

| Scenario | US$ / month |
|---|---|
| 0.5 ACU for 80 active hours | 8 |
| 0.5 ACU all month | 73 |
| 1 ACU all month (the configured ceiling) | 146 |
| Storage (20 GB) and two secrets | about 3 |
| Staging budget alert, used here as a stand-in for total running cost | 40 |

Not priced: Lambda, API Gateway, Amplify, S3, logs, data transfer, taxes. They are small next to Aurora at this scale but have not been measured.

## 3. Break-even

Assumptions (all **unverified**): US$1 = S$1.30; card fee about 3.4% + S$0.50 per payment, so a S$6.90 payment nets about S$6.17; price excludes GST (not checked whether GST applies).

Subscribers needed on the monthly plan = fixed cost in S$ / S$6.17:

| Fixed cost (US$) | Subscribers |
|---|---|
| 8 | 2 |
| 40 | 9 |
| 73 | 16 |
| 146 | 31 |

If everyone took the annual plan (S$59, about S$4.71 / month after fees), the 40 row needs about 12.

Gross margin on the variable AI cost alone is about 99% (S$6.17 net against about S$0.05). The price is therefore set by the fixed platform cost and by what users will pay, not by the AI bill.

## 4. Why S$6.90 and not another number

- It covers the platform at a small number of subscribers (9 for the US$40 case) while the per-user AI cost is cents.
- 50 uses a month is ten times the free limit. Every AI feature on one job shares a single use, so it means 50 different jobs a month, more than most job seekers apply to (an assumption, not measured).
- It is a proposal. **Not done:** a competitor price comparison, a willingness-to-pay check with users, and a decision on GST. Do these (or state them as limitations) before the report.

## 5. To measure before the report

1. Real latency and cost per fit, tailor and cover-letter call from CloudWatch (`/aws/lambda/jobhunter-staging-llm`) and the gateway's token counts (`llm/client.py` records `last_usage` but nothing stores it yet).
2. Actual Aurora ACU-hours and storage over a test week (Billing and CloudWatch), including the Locust runs.
3. Replace the estimates in sections 2 and 3 with those numbers and say which are measured.
