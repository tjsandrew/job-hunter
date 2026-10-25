# Shared staging settings: no passwords, tokens or AWS credentials.
# Include with -var-file=staging.tfvars for every staging plan.
account_id            = "091512051916"
budget_alert_emails   = ["jsandrewtiong@gmail.com"]
activity_alert_emails = ["jsandrewtiong@gmail.com"]
monthly_budget_usd    = 40
enable_backend        = true
api_image_uri         = "091512051916.dkr.ecr.ap-southeast-1.amazonaws.com/jobhunter-staging@sha256:3c45fd7770878fd58f1c5f912de55c520e9596d3e188a165b877e0085fd55072"

# Embedding worker (docs/design/11-EMBEDDING-WORKER.md). Immutable digest of the first worker image (Deploy staging run summary).
# The function ignores later image changes, so this only has to stay non-empty: an empty value would plan to remove the worker.
embed_image_uri = "091512051916.dkr.ecr.ap-southeast-1.amazonaws.com/jobhunter-staging-embed@sha256:34e4c13f5fa430d5d6fae3a5daa8737f24872a267f164e915b04fb40343d4ea2"

# The API writes an S3 flag after a profile or preferences save and the embedding worker does the rest (design brief 11).
embed_on_save = "queue"

# Serve the semantic For you list. Apply only AFTER the Deploy staging run that ships the API with the "still preparing" message.
for_you_enabled = "1"

# Shared LLM worker for fit analysis and the AI resume rewrite (docs/design/12-FIT-ANALYSIS.md). The key comes from the GitHub
# secret LLM_API_KEY at release time. Never apply without this line: the worker would be removed.
llm_worker_enabled = true

# Job pull (docs/design/04-JOB-INGESTION.md): two Lambdas that load a few new public job postings into Aurora when the Pull jobs
# GitHub workflow runs. No schedule (each run wakes Aurora). Never apply without this line: the functions would be removed.
discovery_enabled = true
# Searches cover the evaluation personas and a broader market. A pull rotates between searches, so each batch is
# mixed. Nine searches fetched 2,363 unique Singapore listings in about 3 minutes (dry run, 25 October 2026);
# the discovery function's timeout is 300 seconds.
discovery_mycareersfuture_searches = ["data engineer", "software engineer", "data analyst", "frontend developer",
"backend developer", "devops engineer", "cloud engineer", "business analyst", "product manager"]

# Adzuna (Singapore search verified on 24 October 2026). One request per keyword per pull; the free plan allows very few calls a
# day, so keep this list short. The keys are the GitHub secrets ADZUNA_APP_ID and ADZUNA_APP_KEY; without them Adzuna fails cleanly
# and the other sources still load.
discovery_adzuna_searches = ["data engineer"]
