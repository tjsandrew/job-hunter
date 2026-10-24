# Fit-analysis worker (docs/design/12-FIT-ANALYSIS.md).
#
# The API Lambda runs in a VPC with no internet, so it cannot call the school's SoCLaaS model gateway. It writes a request
# file to S3 (free through the S3 gateway endpoint); S3 invokes this function, which runs OUTSIDE the VPC, calls the model and
# writes the result file next to it. The function has no database access and no network path into the VPC. Nothing here
# needs a NAT gateway.
#
# Off by default: it needs a SoCLaaS key and the course staff's agreement that a deployed group app may use one.
#   fit_worker_enabled = false: nothing below exists and the API keeps FIT_BACKEND=inline (fit analysis answers 503).
#   fit_worker_enabled = true:  the function, its permissions and the bucket notification exist. The key is NOT set here: the
#   release workflow writes it from the GitHub secret LLM_API_KEY (scripts/deploy_aws.py), like the database passwords.

variable "fit_worker_enabled" {
  description = "Create the fit-analysis worker and switch the API to hand fit requests to it through S3."
  type        = bool
  default     = false
}

variable "fit_llm_base_url" {
  description = "OpenAI-compatible endpoint of the model gateway (SoCLaaS)."
  type        = string
  default     = "https://soclaas-api.comp.nus.edu.sg/v1"
}

variable "fit_llm_model" {
  description = "Model used for fit analysis; chosen by benchmark (docs/design/12-FIT-ANALYSIS.md)."
  type        = string
  default     = "gemma4:26b"
}

locals {
  fit_enabled        = var.fit_worker_enabled
  fit_request_prefix = "fit-requests/"
  fit_result_prefix  = "fit-results/"
  # Request and result files hold profile text; they are only needed for the minute the analysis runs.
  fit_prefixes   = [local.fit_request_prefix, local.fit_result_prefix]
  fit_timeout    = 300
  fit_alarm_arns = ["arn:aws:cloudwatch:ap-southeast-1:${var.account_id}:alarm:${var.name}-fit-errors"]
}

resource "aws_iam_role" "fit" {
  name               = "${var.name}-fit"
  assume_role_policy = aws_iam_role.api.assume_role_policy
}
# Logs only: this function is deliberately NOT given the VPC access policy.
resource "aws_iam_role_policy_attachment" "fit_logs" {
  role       = aws_iam_role.fit.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}
resource "aws_iam_role_policy" "fit" {
  role = aws_iam_role.fit.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["s3:GetObject"], Resource = "${aws_s3_bucket.documents.arn}/${local.fit_request_prefix}*" },
    { Effect = "Allow", Action = ["s3:PutObject"], Resource = "${aws_s3_bucket.documents.arn}/${local.fit_result_prefix}*" }
  ] })
}
resource "aws_cloudwatch_log_group" "fit" {
  name              = "/aws/lambda/${var.name}-fit"
  retention_in_days = 7
}

resource "aws_lambda_function" "fit" {
  count         = local.fit_enabled ? 1 : 0
  function_name = "${var.name}-fit"
  role          = aws_iam_role.fit.arn
  package_type  = "Image"
  image_uri     = var.image_uri # the API image; later releases update it (see ignore_changes)
  architectures = ["arm64"]
  image_config { command = ["job_hunter.fit_worker.handler"] }
  memory_size = 512
  timeout     = local.fit_timeout
  # A cost guard: at most three analyses run at once, whatever the traffic.
  reserved_concurrent_executions = 3
  environment {
    variables = {
      DOCUMENT_BUCKET      = aws_s3_bucket.documents.id
      LLM_BASE_URL         = var.fit_llm_base_url
      LLM_MODEL            = var.fit_llm_model
      LLM_REASONING_EFFORT = "none"
      LLM_TIMEOUT_SECONDS  = "90"
    }
  }
  # The release workflow owns the image and the key (LLM_API_KEY comes from a GitHub secret); manual controls own concurrency.
  lifecycle { ignore_changes = [image_uri, reserved_concurrent_executions, environment[0].variables["LLM_API_KEY"]] }
  depends_on = [aws_iam_role_policy_attachment.fit_logs, aws_iam_role_policy.fit, aws_cloudwatch_log_group.fit]
}

resource "aws_lambda_permission" "fit_from_s3" {
  count          = local.fit_enabled ? 1 : 0
  statement_id   = "AllowS3InvokeFit"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.fit[0].function_name
  principal      = "s3.amazonaws.com"
  source_arn     = aws_s3_bucket.documents.arn
  source_account = var.account_id
}

resource "aws_cloudwatch_metric_alarm" "fit_errors" {
  count               = local.fit_enabled ? 1 : 0
  alarm_name          = "${var.name}-fit-errors"
  alarm_description   = "The fit worker returned an error (an unreadable request or a crash; a model outage is reported to the user instead)."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.fit[0].function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.activity.arn]
  depends_on          = [aws_sns_topic_policy.activity]
}

output "fit_function" { value = local.fit_enabled ? aws_lambda_function.fit[0].function_name : "" }
output "fit_arn" { value = local.fit_enabled ? aws_lambda_function.fit[0].arn : "" }
