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

# Job pull (docs/design/04-JOB-INGESTION.md): two Lambdas that load a few new public job postings into Aurora, started by the
# Pull jobs GitHub workflow and by an EventBridge schedule. Never apply without this line: the functions would be removed.
discovery_enabled = true
# Twice a day, 08:00 and 20:00 Singapore time (00:00 and 12:00 UTC). Each pull wakes Aurora for about 30 minutes
# (about USD 0.10), roughly USD 6 a month; the pause workflow also stops scheduled pulls.
discovery_schedule_enabled    = true
discovery_schedule_expression = "cron(0 0,12 * * ? *)"
# New jobs per pull (newest postings first). The 21 searches see roughly 250 new listings a day, so 150 twice a day keeps
# up with the market; jobs close again when they expire or go unseen for 21 days. The code caps one pull at 200.
discovery_max_new = 150
# Searches cover the evaluation personas and a broader market: tech, data and product (the first nine), then finance,
# marketing, people and operations, consulting and design (added 31 October 2026, each checked to return MyCareersFuture
# jobs). A pull rotates between searches, so each batch is mixed. Each search reads at most 5 pages of 100; the nine
# tech searches fetched 2,226 Singapore listings in about 130 seconds, so 21 take about 5-6 minutes (timeout 600 s).
discovery_mycareersfuture_searches = ["data engineer", "software engineer", "data analyst", "frontend developer",
  "backend developer", "devops engineer", "cloud engineer", "business analyst", "product manager",
  "machine learning engineer", "financial analyst", "accountant", "investment analyst", "marketing executive",
  "digital marketing", "hr executive", "operations executive", "supply chain", "management consultant",
"project manager", "ux designer"]

# Adzuna (Singapore search verified on 24 October 2026). One request per keyword per pull; the free plan allows very few calls a
# day, so keep this list short. The keys are the GitHub secrets ADZUNA_APP_ID and ADZUNA_APP_KEY; without them Adzuna fails cleanly
# and the other sources still load.
discovery_adzuna_searches = ["data engineer"]
