# 13 - Pricing and plans (proposal)

Status: **proposal (9 November 2026).** Premium is a demo plan for now: the Upgrade button explains this rather than taking a payment, and a payment gateway is future work. The price below is a modelled number, not a measured or market-tested one. The limits and the free and premium plans are real; the price and the payment flow are the proposal.

## 1. The plans

| | Free | Premium (demo plan; price proposed) |
|---|---|---|
| Price | S$0 | **S$6.90 / month** or **S$59 / year** (about S$4.90 / month, as the app shows it) |
| AI uses per month | 5 | 50 |
| What counts as a use | One job per calendar month (Singapore time). A fit check, "Tailor with AI" and a cover letter written for the same job count **once**, and repeating any of them for that job is free | same |
| Always free, no limit | Rule-based tailoring (reorders bullets), resume builder, PDF export, tracker, Discover | same |

The limits are enforced in code: `preparation/allowance.py` (`LIMITS = {"free": 5, "premium": 50}`, table `ai_tailor_uses`), counted per Singapore calendar month. A user's plan is changed only by an operator, with `scripts/set_plan.py` (through the migrate Lambda; there is no API route). A payment gateway and a self-service plan switch are future work.

## 2. Cost model

**Variable cost: the AI calls.** Only the AI features cost money per use; everything else is a database read or write.

| Item | Value | Source / status |
|---|---|---|
| One fit analysis on the school gateway (measured on `gemma4:26b`) | about US$0.0008, 28-39 s | [design 12](12-FIT-ANALYSIS.md), benchmark of 4 postings and 1 demo profile; estimated from token counts, **not** from a price page. Since 8 Nov 2026 the model is `ornith1.5:35b`: about US$0.0007 and 14–23 s per fit in a 3-case comparison, also estimated from token counts. No SoCLaaS price list was available (B5 assumed the gateway is free to the project) |
| Cover letter and Tailor with AI | time and tokens measured; cost per call not computed | `eval/results/b2-ai-tasks-20261025T130734Z/` (on `gemma4:26b`, deployed app): cover letter P50 11.4 s, 15 of 15 completed, about 1,050 tokens in and 520 out per letter; AI resume rewrite P50 4.3 s, 10 of 15 returned a usable result, about 835 in and 90 out. A fit analysis used about 3,250 in and 1,140 out, so both should cost no more than a fit; the model price is the school gateway's, as for fit |
| Free user at the limit (5 uses) | about US$0.004 / month | 5 x 0.0008 |
| Premium user at the limit (50 uses) | about US$0.04 / month | 50 x 0.0008 |
| Same, if a commercial model cost 50 times more | about US$2 / month | sensitivity only |

The school gateway (SoCLaaS) is a course resource, not a commercial service. The course staff confirmed that the deployed group app may use one shared key; a budget for it was not stated. If the product left the course, the model price would have to be re-measured; the sensitivity row shows the plan would still be above cost.

**Fixed cost: the platform.** Dominated by Aurora Serverless v2 ([deployment README](../deployment/README.md): US$0.20 per ACU-hour, US$0.11 per GB-month, 0-1 ACU, auto-pause after 30 idle minutes). An ACU (Aurora Capacity Unit) is about 2 GiB of memory with matching CPU, billed per hour while the database is awake.

| Scenario | US$ / month |
|---|---|
| 0.5 ACU for 80 active hours | 8 |
| 0.5 ACU all month | 73 |
| 1 ACU all month (the configured ceiling) | 146 |
| Storage (20 GB) and two secrets | about 3 |
| Staging budget alert (a ceiling for the team's budget, **not** a cost estimate) | 40 |

The twice-daily job pull (06:00 and 20:00 Singapore time) wakes Aurora for about 30 minutes each time. `infra/aws/staging.tfvars` estimates this at about US$0.10 a pull, roughly US$6 a month (an estimate, not a bill).

Lambda, API Gateway, Amplify, S3, logs, data transfer and taxes are not priced in this simple model. The B5 cost model (`eval/results/b5-cost-20261026/`) prices them: it projects about US$22 a month for the serverless build at 10 active users, including 9% GST, and about US$86 at 100 users.

## 3. Break-even

Assumptions (all **unverified**):

- US$1 = S$1.30.
- The card fee is about 3.4% + S$0.50 per payment, so a S$6.90 payment nets about S$6.17.
- The price excludes GST (whether GST applies was not checked).

Subscribers needed on the monthly plan = fixed cost in S$ / S$6.17:

| Fixed cost (US$) | Subscribers |
|---|---|
| 8 | 2 |
| 40 | 9 |
| 73 | 16 |
| 146 | 31 |

If everyone took the annual plan (S$59, about S$4.71 / month after fees), the 40 row needs about 11 (52 / 4.71).

Gross margin on the variable AI cost alone is about 99% (S$6.17 net against about S$0.05). The price is therefore set by the fixed platform cost and by what users will pay, not by the AI bill.

## 4. Why S$6.90 and not another number

- It covers the platform at a small number of subscribers (9 for the US$40 case) while the per-user AI cost is cents.
- 50 uses a month is ten times the free limit. Every AI feature on one job shares a single use, so it means 50 different jobs a month, more than most job seekers apply to (an assumption, not measured).
- It is a proposal. Not done: a competitor price comparison, a willingness-to-pay check with users, and a decision on GST.

## 5. Measured so far, and not yet measured

Measured:

- **Aurora usage.** Over 73 hours (22–25 Oct 2026) the database used 6.82 ACU-hours. It was active for 22 hours and fully paused for 51 (`eval/results/a6-aurora-pause-20261025.json`). At US$0.20 per ACU-hour that is about US$1.36 of compute.
- **Actual spend.** Cost Explorer shows US$2.63 in total for 1–25 October 2026. Aurora was US$2.19 of it (`eval/results/b5-cost-20261026/notes.md`).

Not yet measured:

1. Cost per fit, tailor and cover-letter call. The LLM worker logs latency and token counts per request (`/aws/lambda/jobhunter-staging-llm`, event `llm_task`), summarised in `eval/results/b2-ai-tasks-20261025T130734Z/` on `gemma4:26b`. They have not been turned into a measured cost. They have not been repeated on `ornith1.5:35b` (the model since 8 Nov 2026), except the 3-case fit comparison in [design 12](12-FIT-ANALYSIS.md).
2. Storage cost over a longer period, including the Locust load-test runs.

The estimates in sections 2 and 3 stand until measured numbers replace them.
