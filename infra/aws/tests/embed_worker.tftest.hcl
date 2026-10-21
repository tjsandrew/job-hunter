# Mocked plans only: no AWS requests or resource creation.
# Checks the embedding worker's staged rollout (docs/design/11-EMBEDDING-WORKER.md).
mock_provider "aws" {
  mock_data "aws_availability_zones" {
    defaults = { names = ["ap-southeast-1a", "ap-southeast-1b"] }
  }
}

variables {
  name                  = "test-staging"
  account_id            = "123456789012"
  origin                = "https://main.example.amplifyapp.com"
  cognito_issuer        = "https://cognito-idp.ap-southeast-1.amazonaws.com/example"
  client_id             = "test-client"
  image_uri             = "123456789012.dkr.ecr.ap-southeast-1.amazonaws.com/test@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  activity_alert_emails = ["team@example.test"]
}

run "stage_one_creates_the_queue_but_no_function_and_changes_nothing_for_users" {
  command = plan
  module { source = "./backend" }
  assert {
    condition     = length(aws_lambda_function.embed) == 0 && length(aws_lambda_event_source_mapping.embed) == 0 && length(aws_s3_bucket_notification.embed) == 0
    error_message = "Without an image digest only the queue, IAM, alarm and flag expiry exist: no function, mapping or bucket notification."
  }
  assert {
    condition     = aws_sqs_queue.embed.visibility_timeout_seconds == 6 * 900 + 5 && aws_sqs_queue.embed.sqs_managed_sse_enabled && aws_sqs_queue.embed_dlq.sqs_managed_sse_enabled
    error_message = "The queue visibility timeout must be six times the function timeout plus the batching window, and both queues must be encrypted."
  }
  assert {
    condition     = aws_lambda_function.api.environment[0].variables["EMBED_ON_SAVE"] == "0"
    error_message = "The API must not write embed flags until the worker is live."
  }
  assert {
    condition     = anytrue([for rule in aws_s3_bucket_lifecycle_configuration.embed_flags.rule : rule.id == "expire-embed-flags" && rule.filter[0].prefix == "embed-requests/" && rule.expiration[0].days == 1])
    error_message = "Embed flags must expire after a day, and the rule must not touch uploads or exports."
  }
  assert {
    condition     = aws_cloudwatch_metric_alarm.embed_dlq.threshold == 0 && aws_cloudwatch_metric_alarm.embed_dlq.namespace == "AWS/SQS"
    error_message = "Any message in the dead-letter queue must alarm."
  }
}

run "stage_two_creates_the_worker_with_bounded_settings" {
  command = plan
  module { source = "./backend" }
  variables {
    embed_image_uri = "123456789012.dkr.ecr.ap-southeast-1.amazonaws.com/test-embed@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    embed_on_save   = "queue"
  }
  assert {
    condition     = aws_lambda_function.embed[0].memory_size == 3008 && aws_lambda_function.embed[0].timeout == 900 && contains(aws_lambda_function.embed[0].architectures, "arm64")
    error_message = "The worker is arm64, 3008 MB and the Lambda maximum 900 s timeout."
  }
  assert {
    condition     = aws_lambda_function.embed[0].reserved_concurrent_executions == 2 && aws_lambda_event_source_mapping.embed[0].scaling_config[0].maximum_concurrency <= aws_lambda_function.embed[0].reserved_concurrent_executions
    error_message = "The queue mapping's maximum concurrency must not exceed the function's reserved concurrency, or messages are throttled."
  }
  assert {
    condition     = aws_lambda_event_source_mapping.embed[0].batch_size == 10 && aws_lambda_event_source_mapping.embed[0].maximum_batching_window_in_seconds == 5
    error_message = "A burst of flags (up to 10 within 5 s) must collapse into one invocation; the worker ignores flag contents."
  }
  assert {
    condition     = aws_lambda_function.embed[0].image_config[0].command[0] == "job_hunter.embed_worker.handler" && aws_lambda_function.embed[0].environment[0].variables["DATABASE_USERNAME"] == "jobhunter_embedder"
    error_message = "The worker runs its own handler as its own least-privilege database role, never the application role."
  }
  assert {
    condition     = aws_s3_bucket_notification.embed[0].queue[0].filter_prefix == "embed-requests/" && contains(aws_s3_bucket_notification.embed[0].queue[0].events, "s3:ObjectCreated:*")
    error_message = "Only objects created under the flag prefix may wake the worker, so uploads and exports never do."
  }
  assert {
    condition     = aws_lambda_function.api.environment[0].variables["EMBED_ON_SAVE"] == "queue"
    error_message = "EMBED_ON_SAVE=queue must reach the API once the worker exists."
  }
  assert {
    condition     = aws_cloudwatch_metric_alarm.embed_runaway[0].threshold == 60 && aws_cloudwatch_metric_alarm.embed_runaway[0].metric_name == "Invocations"
    error_message = "A runaway guard must alarm when the worker runs far more than a normal save would trigger."
  }
}

run "reject_a_mutable_embed_image" {
  command = plan
  module { source = "./backend" }
  variables {
    embed_image_uri = "123456789012.dkr.ecr.ap-southeast-1.amazonaws.com/test-embed:latest"
  }
  expect_failures = [var.embed_image_uri]
}

run "reject_in_request_embedding_in_aws" {
  command = plan
  module { source = "./backend" }
  variables {
    embed_on_save = "1"
  }
  expect_failures = [var.embed_on_save]
}

run "root_wires_the_embed_repository_and_deployment_outputs" {
  command = plan
  variables {
    enable_backend = true
    api_image_uri  = "123456789012.dkr.ecr.ap-southeast-1.amazonaws.com/test@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  }
  assert {
    condition     = aws_ecr_repository.embed.image_tag_mutability == "IMMUTABLE" && aws_ecr_repository.embed.image_scanning_configuration[0].scan_on_push
    error_message = "The embed worker image repository must be immutable and scanned, like the API's."
  }
  assert {
    condition     = contains(keys(output.deployment), "EMBED_ECR_REPOSITORY") && contains(keys(output.deployment), "EMBED_FUNCTION")
    error_message = "The deployment outputs must publish the embed repository and function names for the GitHub variables."
  }
}
