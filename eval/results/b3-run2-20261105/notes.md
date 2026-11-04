# B3 run 2 rerun: raised-capacity window, main 63b8ff5 (5 November 2026, 01:57–02:21 SGT)

Window (A5 runbook): opened 01:54 SGT with API concurrency 50, gateway 200/s burst 400, Aurora maximum 4 ACU;
restored 02:24 SGT. A plain `terraform plan -var-file=staging.tfvars` from `main` showed **No changes** before
opening and after restoring (`config-before.txt`, `config-after.txt`). Pool 5,905 jobs, kept constant (Save/Pass
undone straight away; no decisions left at the end).

| Users | Served req/s, 26 Oct → 5 Nov | Failed, 26 Oct → 5 Nov | P50 / P95 of served, 5 Nov | API concurrency max | Aurora CPU avg, 26 Oct → 5 Nov |
|---|---|---|---|---|---|
| 1 | 0.3 → 0.4 | 0 → 0 | 38 / 1,883 ms | 1 | 15% → 14% |
| 10 | 3.6 → 3.6 | 0 → 0 | 38 / 2,401 ms | 9 | 29% → 15% |
| 50 | 18.2 → 18.0 | 0 → 0 | 34 / 2,392 ms | 28 | 86% → 19% |
| 100 | 27.5 → **36.7** | 0.8% → **0** | **32 / 2,365 ms** (Oct: 1,158 / 2,794) | 48 of 50 | 100% → **23%** |

- **No saturation within 100 users.** Every request was served, throughput grew in step with load (36.7 req/s is
  what 100 users of this kind generate), latency did not move from 10 users to 100, and there were no function errors.
- **The October bottleneck is gone.** Then, 100 users pinned Aurora at 100% of 4 ACU and doubled function time; now
  Aurora averages 23% CPU (72% peak) and mean function time stays at 0.82–0.89 s. The in-memory job pool and vector
  cache (PRs #46, #48, #49) and connection reuse (PR #50) moved the work off the database.
- **The next limit is the function cap.** Concurrency reached 48 of 50, so somewhat over 100 users of this kind
  would start being throttled even in the raised window. Each listing request holds a function instance for about
  2.3 s, so making the listings faster raises the ceiling directly.
- Aurora reported its 4 ACU maximum from the 10-user step on despite low CPU, so it scaled for another resource
  (most likely memory, with up to 48 connections); its cost in this window is set by ACU, not CPU.
