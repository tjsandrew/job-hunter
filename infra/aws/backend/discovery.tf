# Job pull (docs/design/04-JOB-INGESTION.md): how real job postings reach the staging database.
#
# Aurora is private and the VPC has no internet (no NAT gateway), so one Lambda cannot both read the public job feeds and write
# the database. Two functions share the work, joined by S3 and a direct invoke:
#
#   discovery (OUTSIDE the VPC)  fetches Greenhouse, Lever and MyCareersFuture, stores the normalised records as
#                                imports/<pull id>.json, then invokes
#   import    (INSIDE the VPC)   reads that object through the free S3 gateway endpoint, inserts the next few NEW jobs into
#                                Aurora, and writes the embed flag so the embed worker gives them vectors.
#
# Both run the API image (image_config.command picks the handler). Nothing here needs a NAT gateway or a new bucket
# notification (S3 allows one per bucket; the embed and LLM triggers already use it).
#
# Off by default.
#   discovery_enabled = false: nothing below exists except unused roles and log groups.
#   discovery_enabled = true:  both functions exist. Start a pull with the "Pull jobs" GitHub workflow (scripts/pull_jobs.py).
#   discovery_schedule_enabled = true additionally creates an EventBridge rule that starts a pull on a schedule. Every pull wakes
#   Aurora (it auto-pauses when idle) for about 30 minutes, about USD 0.10 at 1 ACU. A scheduled pull is an asynchronous invoke:
#   it is never retried (a retry would pull twice) and is dropped if it cannot start within an hour, which is what happens
#   while staging is paused (the pause workflow sets this function's concurrency to 0). Errors alarm to the activity topic.

variable "discovery_enabled" {
  description = "Create the job-pull functions (discovery outside the VPC, import inside it)."
  type        = bool
  default     = false
}

variable "discovery_greenhouse_boards" {
  description = "Greenhouse board tokens to read."
  type        = list(string)
  default     = ["stripe", "cloudflare", "coinbase"]
}

variable "discovery_lever_boards" {
  description = "Lever site tokens to read."
  type        = list(string)
  default     = ["lalamove"]
}

variable "discovery_mycareersfuture_searches" {
  description = "MyCareersFuture search keywords; each is read like one board."
  type        = list(string)
  default     = ["data engineer", "software engineer", "data analyst"]
}

variable "discovery_adzuna_searches" {
  description = "Adzuna search keywords. Empty (the default) leaves Adzuna off; add keywords only after the GitHub secrets ADZUNA_APP_ID and ADZUNA_APP_KEY exist."
  type        = list(string)
  default     = []
}

variable "discovery_max_new" {
  description = "How many NEW jobs one pull may add (the Pull jobs workflow can override it per run)."
  type        = number
  default     = 10
}

variable "discovery_schedule_enabled" {
  description = "Also start a pull on a schedule (EventBridge). Wakes Aurora each time; off by default."
  type        = bool
  default     = false
}

variable "discovery_schedule_expression" {
  description = "EventBridge schedule used when discovery_schedule_enabled is true."
  type        = string
  default     = "rate(1 day)"
}

locals {
  discovery_enabled    = var.discovery_enabled
  import_prefix        = "imports/"
  discovery_alarm_arns = ["arn:aws:cloudwatch:ap-southeast-1:${var.account_id}:alarm:${var.name}-discovery-errors"]
  # Built from the name so the discovery role's policy does not depend on a function that only exists when enabled.
  import_function_arn = "arn:aws:lambda:ap-southeast-1:${var.account_id}:function:${var.name}-import"
}

# ---- discovery: outside the VPC, internet access, no database ----
resource "aws_iam_role" "discovery" {
  name               = "${var.name}-discovery"
  assume_role_policy = aws_iam_role.api.assume_role_policy
}
# Logs only: deliberately NOT given the VPC access policy.
resource "aws_iam_role_policy_attachment" "discovery_logs" {
  role       = aws_iam_role.discovery.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}
resource "aws_iam_role_policy" "discovery" {
  role = aws_iam_role.discovery.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    # Write-only: it stores the snapshot but cannot read, list or delete anything.
    { Effect = "Allow", Action = ["s3:PutObject"], Resource = "${aws_s3_bucket.documents.arn}/${local.import_prefix}*" },
    { Effect = "Allow", Action = ["lambda:InvokeFunction"], Resource = local.import_function_arn }
  ] })
}
resource "aws_cloudwatch_log_group" "discovery" {
  name              = "/aws/lambda/${var.name}-discovery"
  retention_in_days = 7
}

resource "aws_lambda_function" "discovery" {
  count         = local.discovery_enabled ? 1 : 0
  function_name = "${var.name}-discovery"
  role          = aws_iam_role.discovery.arn
  package_type  = "Image"
  image_uri     = var.image_uri # the API image; later releases update it (see ignore_changes)
  architectures = ["arm64"]
  image_config { command = ["job_hunter.discovery_worker.handler"] }
  memory_size = 512
  # Reading the feeds (MyCareersFuture waits a second between pages; 21 searches take about 5-6 minutes) plus the import
  # step, which may wait minutes for Aurora to resume after a long pause (the import function's own limit is 240 s).
  timeout                        = 600
  reserved_concurrent_executions = 1
  environment {
    variables = {
      DOCUMENT_BUCKET           = aws_s3_bucket.documents.id
      IMPORT_FUNCTION           = "${var.name}-import"
      GREENHOUSE_BOARDS         = join(",", var.discovery_greenhouse_boards)
      LEVER_BOARDS              = join(",", var.discovery_lever_boards)
      MYCAREERSFUTURE_SEARCHES  = join(",", var.discovery_mycareersfuture_searches)
      ADZUNA_SEARCHES           = join(",", var.discovery_adzuna_searches)
      DISCOVERY_MAX_NEW         = tostring(var.discovery_max_new)
      DISCOVERY_TIMEOUT_SECONDS = "15"
    }
  }
  # The release workflow owns the image and any source keys (ADZUNA_APP_ID / ADZUNA_APP_KEY come from GitHub secrets).
  lifecycle { ignore_changes = [image_uri, reserved_concurrent_executions, environment[0].variables["ADZUNA_APP_ID"], environment[0].variables["ADZUNA_APP_KEY"]] }
  depends_on = [aws_iam_role_policy_attachment.discovery_logs, aws_iam_role_policy.discovery, aws_cloudwatch_log_group.discovery]
}

# ---- import: inside the VPC, can reach Aurora, no internet ----
resource "aws_iam_role" "pull_import" {
  name               = "${var.name}-import"
  assume_role_policy = aws_iam_role.api.assume_role_policy
}
resource "aws_iam_role_policy_attachment" "pull_import_network" {
  role       = aws_iam_role.pull_import.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}
resource "aws_iam_role_policy" "pull_import" {
  role = aws_iam_role.pull_import.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["s3:GetObject"], Resource = "${aws_s3_bucket.documents.arn}/${local.import_prefix}*" },
    # Only to wake the embed worker after new jobs are committed. It cannot read or delete any flag.
    { Effect = "Allow", Action = ["s3:PutObject"], Resource = "${aws_s3_bucket.documents.arn}/${local.embed_flag_prefix}*" }
  ] })
}
resource "aws_cloudwatch_log_group" "pull_import" {
  name              = "/aws/lambda/${var.name}-import"
  retention_in_days = 7
}

resource "aws_lambda_function" "pull_import" {
  count         = local.discovery_enabled ? 1 : 0
  function_name = "${var.name}-import"
  role          = aws_iam_role.pull_import.arn
  package_type  = "Image"
  image_uri     = var.image_uri
  architectures = ["arm64"]
  image_config { command = ["job_hunter.import_worker.handler"] }
  memory_size                    = 512
  timeout                        = 240
  reserved_concurrent_executions = 1 # one writer at a time
  vpc_config {
    subnet_ids         = aws_subnet.private[*].id
    security_group_ids = [aws_security_group.lambda.id]
  }
  environment {
    variables = {
      APP_ENV           = "aws"
      DATABASE_AUTH     = "password"
      DATABASE_USERNAME = "jobhunter_app"
      DATABASE_HOST     = aws_rds_cluster.app.endpoint
      DATABASE_NAME     = aws_rds_cluster.app.database_name
      DOCUMENT_BUCKET   = aws_s3_bucket.documents.id
    }
  }
  # The release injects the database password and the image; manual controls own concurrency.
  lifecycle { ignore_changes = [image_uri, reserved_concurrent_executions, environment[0].variables["DATABASE_PASSWORD"]] }
  depends_on = [aws_iam_role_policy_attachment.pull_import_network, aws_iam_role_policy.pull_import, aws_cloudwatch_log_group.pull_import, aws_rds_cluster_instance.writer]
}

# ---- optional schedule (off by default) ----
resource "aws_cloudwatch_event_rule" "discovery" {
  count               = (local.discovery_enabled && var.discovery_schedule_enabled) ? 1 : 0
  name                = "${var.name}-discovery"
  description         = "Starts a job pull on a schedule. Each run wakes Aurora."
  schedule_expression = var.discovery_schedule_expression
}
resource "aws_cloudwatch_event_target" "discovery" {
  count = (local.discovery_enabled && var.discovery_schedule_enabled) ? 1 : 0
  rule  = aws_cloudwatch_event_rule.discovery[0].name
  arn   = aws_lambda_function.discovery[0].arn
  input = jsonencode({ max_new = var.discovery_max_new })
}
resource "aws_lambda_permission" "discovery_from_schedule" {
  count         = (local.discovery_enabled && var.discovery_schedule_enabled) ? 1 : 0
  statement_id  = "AllowEventBridgeInvokeDiscovery"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.discovery[0].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.discovery[0].arn
}

# Asynchronous invokes (the schedule) only; the Pull jobs workflow invokes synchronously and is not affected.
resource "aws_lambda_function_event_invoke_config" "discovery" {
  count                        = local.discovery_enabled ? 1 : 0
  function_name                = aws_lambda_function.discovery[0].function_name
  maximum_retry_attempts       = 0
  maximum_event_age_in_seconds = 3600
}

resource "aws_cloudwatch_metric_alarm" "discovery_errors" {
  count               = local.discovery_enabled ? 1 : 0
  alarm_name          = "${var.name}-discovery-errors"
  alarm_description   = "A job pull failed (discovery or its import step). Scheduled pulls are not retried; check the discovery and import logs."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.discovery[0].function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.activity.arn]
  depends_on          = [aws_sns_topic_policy.activity]
}

output "discovery_function" { value = local.discovery_enabled ? aws_lambda_function.discovery[0].function_name : "" }
output "discovery_arn" { value = local.discovery_enabled ? aws_lambda_function.discovery[0].arn : "" }
output "import_function" { value = local.discovery_enabled ? aws_lambda_function.pull_import[0].function_name : "" }
output "import_arn" { value = local.discovery_enabled ? aws_lambda_function.pull_import[0].arn : "" }
