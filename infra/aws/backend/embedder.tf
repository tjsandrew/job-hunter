# Embedding worker (docs/design/11-EMBEDDING-WORKER.md).
#
# The API writes an empty flag object to S3 after a save; S3 sends it to an SQS queue; the worker function reads the
# queue, ignores the message, and embeds whatever the database says is pending. Nothing here needs a NAT gateway or a
# paid VPC endpoint: the S3 gateway endpoint is free, and S3 -> SQS -> Lambda are all service-side.
#
# Rollout is staged so each step is small and reviewable:
#   stage 1 (embed_image_uri = ""): queue, dead-letter queue, queue policy, flag expiry, IAM, log group, alarm. No function.
#   stage 2 (embed_image_uri = digest): the function, its queue mapping, the bucket notification, the function alarms.
# Idle cost is $0 in both stages; SQS and Lambda bill per request/run.

variable "embed_image_uri" {
  description = "Immutable ECR digest of the embed worker image. Empty creates only the stage-1 resources."
  type        = string
  default     = ""
  validation {
    condition     = var.embed_image_uri == "" || can(regex("@sha256:[a-f0-9]{64}$", var.embed_image_uri))
    error_message = "Use an immutable ECR image digest, not a mutable tag."
  }
}
variable "embed_on_save" {
  description = "API behaviour after a profile save: 0 (off) or queue (write the S3 flag). Set queue only once the worker is live."
  type        = string
  default     = "0"
  validation {
    condition     = contains(["0", "queue"], var.embed_on_save)
    error_message = "embed_on_save must be 0 or queue (the in-request embed needs the local HTTP embedder, which AWS does not have)."
  }
}
variable "for_you_enabled" {
  description = "1 serves the semantic For you list (GET /v1/recommendations/for-you); 0 answers 404 FOR_YOU_DISABLED and the web app hides the toggle. Needs embed_on_save = queue, or no profile vector is ever produced."
  type        = string
  default     = "0"
  validation {
    condition     = contains(["0", "1"], var.for_you_enabled)
    error_message = "for_you_enabled must be 0 or 1."
  }
}

locals {
  embed_enabled = var.embed_image_uri != ""
  embed_timeout = 900
  # Up to embed_batch_size flags that are already waiting are handed to one invocation. Every flag means the same thing
  # ("look at the database") and the worker ignores their contents, so collapsing a burst is safe. The window is 0 on purpose:
  # the worker starts as soon as a flag arrives (a lone save waits for nothing), and flags that pile up while it runs are
  # collected into the next invocation. A positive window would collapse bursts further but delay every save by that long.
  embed_batch_window = 0
  embed_batch_size   = 10
  embed_flag_prefix  = "embed-requests/"
  embed_alarm_names  = ["embed-dlq", "embed-errors", "embed-runaway"]
  embed_alarm_arns   = [for name in local.embed_alarm_names : "arn:aws:cloudwatch:ap-southeast-1:${var.account_id}:alarm:${var.name}-${name}"]
}

# ---- queue: S3 flag -> SQS -> worker ----
resource "aws_sqs_queue" "embed_dlq" {
  name                      = "${var.name}-embed-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}
resource "aws_sqs_queue" "embed" {
  name = "${var.name}-embed"
  # AWS guidance for Lambda queue consumers: at least six times the function timeout plus the batching window.
  visibility_timeout_seconds = local.embed_timeout * 6 + local.embed_batch_window
  message_retention_seconds  = 86400
  sqs_managed_sse_enabled    = true
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.embed_dlq.arn
    maxReceiveCount     = 5
  })
}
resource "aws_sqs_queue_policy" "embed" {
  queue_url = aws_sqs_queue.embed.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "s3.amazonaws.com" }, Action = "sqs:SendMessage", Resource = aws_sqs_queue.embed.arn
    Condition = {
      ArnEquals    = { "aws:SourceArn" = aws_s3_bucket.documents.arn }
      StringEquals = { "aws:SourceAccount" = var.account_id }
    }
  }] })
}

# Flags are empty and meaningless after the worker has run. The bucket is versioned, so expire the current version, its
# noncurrent versions and the leftover delete markers. (S3 allows one lifecycle configuration per bucket: add any future
# rule for this bucket here instead of creating a second resource.)
resource "aws_s3_bucket_lifecycle_configuration" "embed_flags" {
  bucket = aws_s3_bucket.documents.id
  rule {
    id     = "expire-embed-flags"
    status = "Enabled"
    filter { prefix = local.embed_flag_prefix }
    expiration { days = 1 }
    noncurrent_version_expiration { noncurrent_days = 1 }
  }
  rule {
    id     = "remove-expired-embed-flag-markers"
    status = "Enabled"
    filter { prefix = local.embed_flag_prefix }
    expiration { expired_object_delete_marker = true }
  }
  depends_on = [aws_s3_bucket_versioning.documents]
}

# ---- identity, logs ----
resource "aws_iam_role" "embed" {
  name               = "${var.name}-embed"
  assume_role_policy = aws_iam_role.api.assume_role_policy
}
resource "aws_iam_role_policy_attachment" "embed_network" {
  role       = aws_iam_role.embed.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}
resource "aws_iam_role_policy" "embed" {
  role = aws_iam_role.embed.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    # The queue mapping polls with the function's role.
    { Effect = "Allow", Action = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"], Resource = aws_sqs_queue.embed.arn },
    # Only to write a follow-up flag when a run ran out of time. It cannot read or delete any object.
    { Effect = "Allow", Action = ["s3:PutObject"], Resource = "${aws_s3_bucket.documents.arn}/${local.embed_flag_prefix}*" }
  ] })
}
resource "aws_cloudwatch_log_group" "embed" {
  name              = "/aws/lambda/${var.name}-embed"
  retention_in_days = 7
}

# ---- stage 2: the function, its queue mapping and the bucket notification ----
resource "aws_lambda_function" "embed" {
  count         = local.embed_enabled ? 1 : 0
  function_name = "${var.name}-embed"
  role          = aws_iam_role.embed.arn
  package_type  = "Image"
  image_uri     = var.embed_image_uri
  architectures = ["arm64"]
  image_config { command = ["job_hunter.embed_worker.handler"] }
  # About 1 GB peak at batch size 1; more memory means more CPU, and local timings give the same cost per job as 2 GB.
  memory_size = 3008
  timeout     = local.embed_timeout
  # Must be at least the queue mapping's maximum concurrency. The pause control sets this to 0.
  reserved_concurrent_executions = 2
  vpc_config {
    subnet_ids         = aws_subnet.private[*].id
    security_group_ids = [aws_security_group.lambda.id]
  }
  environment {
    variables = {
      APP_ENV           = "aws"
      DATABASE_AUTH     = "password"
      DATABASE_USERNAME = "jobhunter_embedder"
      DATABASE_HOST     = aws_rds_cluster.app.endpoint
      DATABASE_NAME     = aws_rds_cluster.app.database_name
      DOCUMENT_BUCKET   = aws_s3_bucket.documents.id
    }
  }
  # Manual controls own concurrency after creation (as for the API); the release injects the database password.
  lifecycle { ignore_changes = [image_uri, reserved_concurrent_executions, environment[0].variables["DATABASE_PASSWORD"]] }
  depends_on = [aws_iam_role_policy_attachment.embed_network, aws_iam_role_policy.embed, aws_cloudwatch_log_group.embed, aws_rds_cluster_instance.writer]
}
resource "aws_lambda_event_source_mapping" "embed" {
  count            = local.embed_enabled ? 1 : 0
  event_source_arn = aws_sqs_queue.embed.arn
  function_name    = aws_lambda_function.embed[0].arn
  batch_size       = local.embed_batch_size
  # Flags that queue up while the worker runs are drained together, not one invocation each.
  maximum_batching_window_in_seconds = local.embed_batch_window
  scaling_config { maximum_concurrency = 2 }
}
resource "aws_s3_bucket_notification" "embed" {
  count  = local.embed_enabled ? 1 : 0
  bucket = aws_s3_bucket.documents.id
  queue {
    queue_arn     = aws_sqs_queue.embed.arn
    events        = ["s3:ObjectCreated:*"]
    filter_prefix = local.embed_flag_prefix
  }
  # Uploads and exports never trigger the worker: only the flag prefix does.
  depends_on = [aws_sqs_queue_policy.embed]
}

# ---- alarms (notification only, through the existing activity topic) ----
resource "aws_cloudwatch_metric_alarm" "embed_dlq" {
  alarm_name          = "${var.name}-embed-dlq"
  alarm_description   = "A flag message failed five times and moved to the dead-letter queue. Embeddings may be stuck; check the embed function logs."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.embed_dlq.name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.activity.arn]
  depends_on          = [aws_sns_topic_policy.activity]
}
resource "aws_cloudwatch_metric_alarm" "embed_errors" {
  count               = local.embed_enabled ? 1 : 0
  alarm_name          = "${var.name}-embed-errors"
  alarm_description   = "The embed function returned an error."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.embed[0].function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.activity.arn]
  depends_on          = [aws_sns_topic_policy.activity]
}
resource "aws_cloudwatch_metric_alarm" "embed_runaway" {
  count               = local.embed_enabled ? 1 : 0
  alarm_name          = "${var.name}-embed-runaway"
  alarm_description   = "The embed function ran more than 60 times in an hour. A normal save runs it once; check for a loop before it costs money."
  namespace           = "AWS/Lambda"
  metric_name         = "Invocations"
  dimensions          = { FunctionName = aws_lambda_function.embed[0].function_name }
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 60
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.activity.arn]
  depends_on          = [aws_sns_topic_policy.activity]
}

output "embed_function" { value = local.embed_enabled ? aws_lambda_function.embed[0].function_name : "" }
output "embed_arn" { value = local.embed_enabled ? aws_lambda_function.embed[0].arn : "" }
output "embed_queue" { value = { queue_url = aws_sqs_queue.embed.id, dead_letter_queue_url = aws_sqs_queue.embed_dlq.id } }
