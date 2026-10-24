# Shared LLM worker (docs/design/12-FIT-ANALYSIS.md): one Lambda for every feature that needs a language model.
# Today its tasks are `fit` (job fit analysis) and `tailor` (AI resume rewrite); a new AI feature adds a task in
# backend/src/job_hunter/llm/tasks.py, not a new Lambda.
#
# The API Lambda runs in a VPC with no internet, so it cannot call the school's SoCLaaS model gateway. It writes a request
# file to S3 (free through the S3 gateway endpoint); S3 invokes this function, which runs OUTSIDE the VPC, calls the model and
# writes the result file next to it. The function has no database access and no network path into the VPC. Nothing here
# needs a NAT gateway.
#
# Off by default: it needs a SoCLaaS key and the course staff's agreement that a deployed group app may use one.
#   llm_worker_enabled = false: nothing below exists and the API keeps LLM_WORKER=inline (AI features answer 503).
#   llm_worker_enabled = true:  the function, its permissions and the bucket notification exist. The key is NOT set here: the
#   release workflow writes it from the GitHub secret LLM_API_KEY (scripts/deploy_aws.py), like the database passwords.

variable "llm_worker_enabled" {
  description = "Create the shared LLM worker and switch the API to hand AI requests (fit analysis, resume rewrite) to it through S3."
  type        = bool
  default     = false
}

variable "llm_base_url" {
  description = "OpenAI-compatible endpoint of the model gateway (SoCLaaS)."
  type        = string
  default     = "https://soclaas-api.comp.nus.edu.sg/v1"
}

variable "llm_model" {
  description = "Model used by every task; chosen by benchmark (docs/design/12-FIT-ANALYSIS.md, fit-tools/TAILOR-BENCHMARK-RESULTS.md)."
  type        = string
  default     = "gemma4:26b"
}

variable "llm_max_concurrency" {
  description = "Most requests the worker handles at once. A cost and rate-limit guard for the shared SoCLaaS key: AWS keeps 10 unreserved concurrency, so the account limit must cover every reservation plus 10."
  type        = number
  default     = 5
}

locals {
  llm_enabled        = var.llm_worker_enabled
  llm_request_prefix = "llm-requests/"
  llm_result_prefix  = "llm-results/"
  # Request and result files hold profile and resume text; they are only needed for the seconds a request runs.
  llm_prefixes = [local.llm_request_prefix, local.llm_result_prefix]
  # The first version of this worker used fit-requests/ and fit-results/. Keep expiring them until the objects written before
  # the rename are gone (about a week after the apply), then delete this local and its use in embedder.tf.
  llm_legacy_prefixes = ["fit-requests/", "fit-results/"]
  llm_timeout         = 300
  llm_alarm_arns      = ["arn:aws:cloudwatch:ap-southeast-1:${var.account_id}:alarm:${var.name}-llm-errors"]
}

resource "aws_iam_role" "llm" {
  name               = "${var.name}-llm"
  assume_role_policy = aws_iam_role.api.assume_role_policy
}
# Logs only: this function is deliberately NOT given the VPC access policy.
resource "aws_iam_role_policy_attachment" "llm_logs" {
  role       = aws_iam_role.llm.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}
resource "aws_iam_role_policy" "llm" {
  role = aws_iam_role.llm.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["s3:GetObject"], Resource = "${aws_s3_bucket.documents.arn}/${local.llm_request_prefix}*" },
    { Effect = "Allow", Action = ["s3:PutObject"], Resource = "${aws_s3_bucket.documents.arn}/${local.llm_result_prefix}*" }
  ] })
}
resource "aws_cloudwatch_log_group" "llm" {
  name              = "/aws/lambda/${var.name}-llm"
  retention_in_days = 7
}

resource "aws_lambda_function" "llm" {
  count         = local.llm_enabled ? 1 : 0
  function_name = "${var.name}-llm"
  role          = aws_iam_role.llm.arn
  package_type  = "Image"
  image_uri     = var.image_uri # the API image; later releases update it (see ignore_changes)
  architectures = ["arm64"]
  image_config { command = ["job_hunter.llm_worker.handler"] }
  memory_size = 512
  timeout     = local.llm_timeout
  # A cost guard: at most this many requests run at once, whatever the traffic.
  reserved_concurrent_executions = var.llm_max_concurrency
  environment {
    variables = {
      DOCUMENT_BUCKET      = aws_s3_bucket.documents.id
      LLM_BASE_URL         = var.llm_base_url
      LLM_MODEL            = var.llm_model
      LLM_REASONING_EFFORT = "none"
      LLM_TIMEOUT_SECONDS  = "90"
    }
  }
  # The release workflow owns the image and the key (LLM_API_KEY comes from a GitHub secret); manual controls own concurrency.
  lifecycle { ignore_changes = [image_uri, reserved_concurrent_executions, environment[0].variables["LLM_API_KEY"]] }
  depends_on = [aws_iam_role_policy_attachment.llm_logs, aws_iam_role_policy.llm, aws_cloudwatch_log_group.llm]
}

resource "aws_lambda_permission" "llm_from_s3" {
  count          = local.llm_enabled ? 1 : 0
  statement_id   = "AllowS3InvokeLlm"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.llm[0].function_name
  principal      = "s3.amazonaws.com"
  source_arn     = aws_s3_bucket.documents.arn
  source_account = var.account_id
}

resource "aws_cloudwatch_metric_alarm" "llm_errors" {
  count               = local.llm_enabled ? 1 : 0
  alarm_name          = "${var.name}-llm-errors"
  alarm_description   = "The LLM worker returned an error (an unreadable request or a crash; a model outage is reported to the user instead)."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.llm[0].function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.activity.arn]
  depends_on          = [aws_sns_topic_policy.activity]
}

output "llm_function" { value = local.llm_enabled ? aws_lambda_function.llm[0].function_name : "" }
output "llm_arn" { value = local.llm_enabled ? aws_lambda_function.llm[0].arn : "" }
