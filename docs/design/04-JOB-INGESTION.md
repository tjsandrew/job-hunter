# 04 — Job discovery, normalisation and shared processing

How real Singapore job postings reach the shared job pool, and how the same posting found on two sites is kept to one card. This is one pool for every user, not a per-user scraper. The operating steps (switching pulls on, checking logs) are in the [job pull runbook](../deployment/JOB-PULL-ROLLOUT.md); the AWS picture is in [what runs where](../architecture/aws-overview.md). Shared names and paths: [CONTRACTS](CONTRACTS.md).

## Approach and why

- **Several kinds of source, because each has a different gap.** Employer boards (Greenhouse, Lever, SmartRecruiters) give complete, current postings from the employers we list, but only those employers. MyCareersFuture, the national job portal, gives breadth across Singapore employers. Adzuna is an aggregator that adds another view and overlaps with the others, which makes cross-source duplicates a real case to handle. No combination is comprehensive: coverage is biased towards the employers and searches we configure, and the app says so rather than promising everything.
- **Only documented, public endpoints.** The adapters call each provider's published job API. Sources that refuse automated access are not used.
- **Singapore only.** A job is kept only if its source location text includes Singapore. A Singapore mention in the description, an employer headquartered in Singapore, or "remote worldwide" does not count.
- **Fetching and importing are split across two Lambdas.** The database sits in a private VPC with no internet; the job feeds are on the internet. One function can reach one or the other, never both, so a *discovery* function outside the VPC fetches and an *import* function inside it writes to the database. Why this beats a NAT gateway or paid VPC endpoints: it costs nothing extra. See [01 Infrastructure](01-INFRASTRUCTURE.md).
- **Each pull imports a bounded batch.** Instead of per-source cursors, leases and resumable checkpoints, every pull re-reads its sources and loads the next batch of jobs that are not stored yet. Whatever does not fit is still listed at the source, so the next pull picks it up. There is nothing to get stuck or to lose.
- **Duplicates are linked, never deleted, and only on exact evidence.** A wrong merge hides a real job from users, while a missed duplicate only shows one extra card. The design therefore prefers to miss a duplicate (see the measured numbers below).
- **Closing a job needs proof.** A source that failed, was cut short or was not polled never closes anything.

## As built

### Sources

| Source | How it is read | In staging |
|---|---|---|
| Greenhouse | public board API, whole board at once | Stripe, Cloudflare, Coinbase |
| Lever | public postings API | Lalamove |
| SmartRecruiters | public company API | adapter exists, not configured |
| MyCareersFuture | keyword search, up to five pages of 100 per search, no key | 21 keyword searches (tech, data and product, then finance, marketing, people and operations, consulting and design) |
| Adzuna | Singapore keyword search, one request per keyword (up to 50 jobs), needs `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` | one keyword, "data engineer" |

The code is `backend/src/job_hunter/ingestion/discovery.py`. Adzuna's free plan allows very few calls a day, and its description is only a snippet. The keys are GitHub secrets written into the Discovery function by the **Deploy staging** workflow; they are never in Terraform, a snapshot or a log.

Each adapter produces the same normalised record:

- **Identity:** source, board and external ID, and the listing URL.
- **Posting:** title, employer, location, work mode and description.
- **Salary**, when stated: minimum, maximum, currency and period.
- **Times:** posting and closing times when given, and the time it was fetched.

Anything a source does not state stays empty rather than guessed, and the posting date is kept apart from the fetch time.

### The pull path in AWS

1. An **EventBridge schedule** (06:00 and 20:00 Singapore time) or the **Pull jobs** GitHub workflow invokes the **Discovery Lambda**.
2. Discovery reads every configured source, keeps Singapore jobs, and writes one snapshot, `imports/<pull_id>.json`, to the private documents bucket.
3. It invokes the **Import Lambda** directly and waits for its counts. The Import Lambda runs inside the VPC and reads the snapshot over the free S3 gateway endpoint.
4. The import **mixes the sources** so a small batch is not all one employer. It takes jobs round-robin over each board or search, newest postings first within each. It then inserts up to N jobs that are not stored yet, as the `jobhunter_app` database role. Jobs already stored are refreshed.
5. It links duplicates, closes listings that have expired or gone unseen (below), and, after the commit, writes the **embed flag** so the embed worker gives the new jobs vectors ([11](11-EMBEDDING-WORKER.md)).

N is 150 for scheduled pulls, 100 by default for the workflow, and never more than 200. Discovery asks each source with a 15-second request timeout. A board or search that times out or answers 5xx or 429 is retried once. After three such failures in a row, that source's remaining searches are skipped for the pull. A source that is down therefore cannot use up the function's time. A scheduled pull is never retried, because a retry would pull twice. Every pull writes one `pull_finished` JSON log line with its counts, and a failed pull raises an alarm.

Locally there is no schedule: `make import-jobs` runs the same code by hand and saves a snapshot, and `make replay-jobs` re-imports the last snapshot without contacting any source ([local development](../LOCAL-DEVELOPMENT.md)).

### Classification at ingestion

Each job gets a role family (`category`) and a seniority level when it is imported, from its title and any level the source states (`job_classification.py`). Matching uses them for its role and level checks ([05](05-RECOMMENDATIONS.md)). The category is always inferred and keeps the title phrase it matched. The seniority is marked "stated" when the source gives a level, and inferred from the title otherwise.

### Deduplication

`(source, source_board, external_id)` identifies a row within a source, so repeating a pull creates no new row. Across sources, `ingestion/dedup.py` links rows that are the same posting without deleting any of them:

- `jobs.match_key` is the normalised employer, title and location. Legal words such as "Pte Ltd" are ignored; level words in the title are kept, so "Senior Data Engineer" and "Data Engineer" stay different.
- `jobs.canonical_job_id` is empty on the row users see and points to that row on its duplicates.
- `jobs.also_seen_on` lists the other sources on the canonical row. The app shows it as "Also on …".

Two rows from **different** sources are linked only if they share a listing URL, or share the `match_key` **and** their descriptions are near-identical text (word-set similarity of 0.6 or more, which also accepts an aggregator's shortened copy). Similar titles alone never merge, and rows of one source never merge.

The canonical row is an open one if any is open, then the most authoritative source (employer board, then MyCareersFuture, then Adzuna), then the earlier posting date, then the ID. The result therefore does not depend on which source was polled first. Discover, For you and embedding skip duplicates; saving a duplicate hides its canonical row for that user. The migration is `0016`; `python -m job_hunter.import_jobs --relink` fills links for older rows.

**Measured accuracy** (`eval/dedup_eval.py`, results in `eval/results/b4-dedup-20261026/`, labelled pairs in `eval/dedup/staging_pairs.json`):

- Staging pulls gave 84 labelled pairs, each labelled by reading both postings. On the 73 scored (11 duplicates, 62 look-alikes) it made **no false merges** (precision 1.00) and found 4 of the 11 duplicates (recall 0.36).
- The missed duplicates are mostly the same posting under differently written employer names ("IG Group" against "IG Asia Pte. Ltd."), so their `match_key` differs although the descriptions match.
- The alternative of matching on description text alone would find more duplicates but at precision 0.34 with the same threshold, which means it would hide many different jobs. We accepted the low recall to avoid that.
- The 16 synthetic pairs in `backend/tests/fixtures/dedup_pairs.json` score 1.00 and 1.00. They are a regression guard that the threshold was tuned on, not a measure of real-world accuracy.

### Changed and closing listings

A listing whose content changes is updated in place and queued for re-embedding. There are no separate job versions.

Every pull closes open jobs past their closing date, and jobs their source has not listed for 21 days (judged by `fetched_at`). The 21-day rule applies only where the pull read the source in full: an employer board fetched without error and not cut short, or a keyword source (MyCareersFuture, Adzuna) whose searches all ran without error. A board that failed, was truncated or was not polled closes nothing. A closed job that a source lists again reopens. Closing does apply to saved and applied jobs: they stay in Saved and the tracker and can still be opened by ID. A closed canonical row hands over to an open copy from another source. Discover and For you also hide a job the moment its closing date passes, since pulls are only twice a day. Each job card shows when it was posted and when the source was last checked.

### What ingestion does not do

- **No requirement extraction at ingestion.** A job's requirements are extracted on demand by fit analysis and cached for all users ([12](12-FIT-ANALYSIS.md)). This way only jobs a user actually opens cost a model call.
- **No per-source run records or checkpoints**, for the reason given above. The `pull_finished` log line is the record of each pull's counts.
- **Vectors are not made here.** Import only sets the flag; the embed worker does the work.

## Known limits

- Coverage is limited to the configured boards and searches. MyCareersFuture is sometimes slow, which is why the morning pull moved from 08:00 to 06:00.
- Adzuna gives short descriptions and very few calls a day, so it is a small part of the pool.
- Work mode is mostly unstated: in the 25 October 2026 evaluation only Lever listings stated one ([evaluation notes](../../eval/README.md)).
- Duplicate detection misses postings whose employer name is written differently on two sites.

## Tests and evaluation

- Pytest with checked-in synthetic provider responses covers each adapter's field mapping, pagination and error handling (`test_ingestion.py`, `test_adzuna.py`), the import, closing and relinking rules (`test_import_jobs.py`, `test_job_pull.py`), classification (`test_job_classification.py`) and deduplication (`test_dedup.py`). Unit tests do not call a live job API.
- Live retrieval and pulls are measured separately in the evaluation scripts `eval/b4_pull.py` and `eval/analyse_b4.py` (pull volume, failures and stage times); see the [evaluation README](../../eval/README.md).
