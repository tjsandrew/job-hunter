# B4 notes: job pipeline and duplicate removal

## Volume and reliability (5 pulls, 24–26 October 2026)

- **Each pull fetches about 2,170 Singapore postings** since the per-search rotation (PR #31) added nine MyCareersFuture
  searches (about 1,090 before): MyCareersFuture about 2,050, Greenhouse 58, Adzuna 50, Lever 11.
- **One source failure in five pulls:** Cloudflare's Greenhouse board exceeded the 8 MB response limit once
  (24 October); the other four pulls had none. No malformed records and no rate limiting were seen.
- **Two searches are truncated on every pull** (`mycareersfuture:software engineer`, `adzuna:data engineer`): they have
  more postings than one pull reads, so some postings are never seen.
- **The import cap, not the sources, limits growth.** The measured pull added its batch of 10 new jobs, found 442
  already stored, and left 1,717 for later pulls. At the workflow's default batch of 10, the backlog alone would take
  about 170 pulls to load.
- Planned: about 10 pulls over a week. Five are recorded so far (the first four from their snapshots and Lambda logs;
  new / stored / deferred counts exist only for pulls run with `eval/b4_pull.py`, because the workflow's job summary
  is not kept). Further pulls can be added with `eval/b4_pull.py` and re-tallied with `eval/analyse_b4.py`.

## Processing latency (measured pull, 26 October 04:17 UTC)

| Stage | Time from discovery start |
|---|---|
| Discovery fetching the feeds | about 154 s |
| Import finished (10 new jobs in the database, visible in All jobs) | 167.9 s |
| Embedding finished (the new jobs can rank in For you) | 193.2 s |

- **Discovery time varies widely and is approaching its limit:** 29, 108, 38, 94 and 167 s across the five pulls,
  against a 300 s function timeout. More searches or boards, or slower feeds, could make a pull time out.
- The embedding worker took 17 s (7 s of it loading the model on a cold start) once the import requested it.
- There is no schedule (each pull is started from the workflow, so it does not wake Aurora unprompted); the maximum
  discovery delay is therefore however long the team waits between pulls.

## Duplicate-removal accuracy

`eval/dedup_eval.py` on `eval/dedup/staging_pairs.json`: 84 real pairs from the pulls, labelled by reading both
postings without the algorithm's verdict (11 cross-source duplicates, 62 hard non-duplicates chosen for shared
employers, titles or text, 1 unsure pair left out, 10 same-source reposts scored separately). See
`../b4-dedup-20261026/summary.md`.

| Set | Precision | Recall | F1 |
|---|---|---|---|
| Real pairs from staging | **1.00** | **0.36** (4 of 11) | 0.53 |
| Synthetic fixture (the set the threshold was tuned on) | 1.00 | 1.00 | 1.00 |

- **No false merges**, even among pairs that share an employer's boilerplate or a title.
- **All 7 misses have the same cause: the exact employer + title key differs**, while the descriptions match well
  (similarity 0.68–0.85, above the 0.6 threshold). Adzuna often names the employer differently ("IG Group" vs "IG
  Asia Pte Ltd", "Google LLC" vs "Google Asia Pacific", the JPMorgan subsidiary "Aumni") or rewrites the title and
  summary. Changing the threshold makes no difference (the sweep is flat).
- **What-if rules** (not in production): matching on text alone finds all 11 but merges far too much (precision 0.34
  at 0.6); matching the employer's first distinctive word plus text gives the best F1, 0.77 (10 of 11 found,
  precision 0.67). The current rule is a deliberate precision-first choice: a wrong merge hides a real job, a missed
  one shows a near-duplicate. The non-duplicates here were picked to be hard, so precision on ordinary postings would
  be higher than these what-if figures.
- **Cross-source duplicates are rare in this data:** about 2 per pull by the production rules, out of about 2,170.
- **Same-source reposts are common and out of scope:** MyCareersFuture has 1,073 pairs with the same employer and
  title in one pull; all 10 sampled were identical text with different posting dates. The design never merges two
  rows of one source, so these appear as repeated listings.
- **Staging spot check:** none of the 210 jobs visible to a test account has an "also seen on" link. Of the four
  pairs the rules catch, at most one row each is in the staging pool (the import has loaded 518 of the ~2,170
  postings), so there was no merged pair to inspect.
