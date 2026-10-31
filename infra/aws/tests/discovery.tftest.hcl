# Mocked plans only: no AWS requests or resource creation.
# Checks the job pull (docs/design/04-JOB-INGESTION.md): off by default, discovery outside the VPC, import inside it, narrow S3
# access, no new bucket notification, and a schedule that exists only when asked for.
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

run "the_job_pull_is_off_by_default" {
  command = plan
  module { source = "./backend" }
  assert {
    condition     = length(aws_lambda_function.discovery) == 0 && length(aws_lambda_function.pull_import) == 0 && length(aws_cloudwatch_event_rule.discovery) == 0
    error_message = "Without discovery_enabled there are no job-pull functions and no schedule."
  }
  assert {
    condition     = length(aws_s3_bucket_notification.embed) == 0
    error_message = "The job pull never uses a bucket notification."
  }
}

run "discovery_has_internet_and_import_has_the_database" {
  command = plan
  module { source = "./backend" }
  variables {
    discovery_enabled = true
  }
  assert {
    condition     = length(aws_lambda_function.discovery[0].vpc_config) == 0
    error_message = "Discovery must run outside the VPC: it has to reach the public job feeds and must not reach the database."
  }
  assert {
    condition     = length(aws_lambda_function.pull_import[0].vpc_config) == 1 && aws_lambda_function.pull_import[0].environment[0].variables["DATABASE_USERNAME"] == "jobhunter_app"
    error_message = "Import runs inside the VPC with the application database role (the jobs table is shared and has no row-level security)."
  }
  assert {
    condition     = aws_lambda_function.discovery[0].function_name == "test-staging-discovery" && aws_lambda_function.pull_import[0].function_name == "test-staging-import" && aws_lambda_function.discovery[0].environment[0].variables["IMPORT_FUNCTION"] == "test-staging-import"
    error_message = "Discovery invokes the import function by name."
  }
  assert {
    condition     = aws_lambda_function.discovery[0].image_config[0].command[0] == "job_hunter.discovery_worker.handler" && aws_lambda_function.pull_import[0].image_config[0].command[0] == "job_hunter.import_worker.handler"
    error_message = "Both functions run the API image with their own handler."
  }
  assert {
    condition     = aws_lambda_function.discovery[0].reserved_concurrent_executions == 1 && aws_lambda_function.pull_import[0].reserved_concurrent_executions == 1 && contains(aws_lambda_function.discovery[0].architectures, "arm64")
    error_message = "One pull and one writer at a time, on arm64."
  }
  assert {
    condition     = !contains(keys(aws_lambda_function.pull_import[0].environment[0].variables), "DATABASE_PASSWORD") && !contains(keys(aws_lambda_function.discovery[0].environment[0].variables), "ADZUNA_APP_KEY")
    error_message = "Passwords and source keys must not be in Terraform state: the release workflow sets them."
  }
  assert {
    condition     = aws_lambda_function.discovery[0].environment[0].variables["GREENHOUSE_BOARDS"] == "stripe,cloudflare,coinbase" && aws_lambda_function.discovery[0].environment[0].variables["DISCOVERY_MAX_NEW"] == "10"
    error_message = "The default sources and the batch size of ten reach the function."
  }
  assert {
    condition     = aws_lambda_function.discovery[0].environment[0].variables["ADZUNA_SEARCHES"] == ""
    error_message = "Adzuna is off until keywords are set."
  }
  assert {
    condition     = length(aws_s3_bucket_notification.embed) == 0
    error_message = "The job pull must not add a bucket notification."
  }
  assert {
    condition     = anytrue([for rule in aws_s3_bucket_lifecycle_configuration.embed_flags.rule : rule.id == "expire-imports" && rule.expiration[0].days == 7])
    error_message = "Snapshots under imports/ expire after a week."
  }
  assert {
    condition     = length(aws_cloudwatch_event_rule.discovery) == 0
    error_message = "No schedule unless discovery_schedule_enabled is true."
  }
  assert {
    condition     = aws_lambda_function_event_invoke_config.discovery[0].maximum_retry_attempts == 0 && aws_lambda_function_event_invoke_config.discovery[0].maximum_event_age_in_seconds == 3600
    error_message = "An asynchronous (scheduled) pull is never retried, and is dropped if it cannot start within an hour (for example while paused)."
  }
  assert {
    condition     = aws_cloudwatch_metric_alarm.discovery_errors[0].metric_name == "Errors" && aws_cloudwatch_metric_alarm.discovery_errors[0].threshold == 0 && aws_cloudwatch_metric_alarm.discovery_errors[0].alarm_name == "test-staging-discovery-errors"
    error_message = "Any failed pull alarms to the team."
  }
}

run "the_schedule_exists_only_when_asked_for" {
  command = plan
  module { source = "./backend" }
  variables {
    discovery_enabled          = true
    discovery_schedule_enabled = true
  }
  assert {
    condition     = length(aws_cloudwatch_event_rule.discovery) == 1 && aws_cloudwatch_event_rule.discovery[0].schedule_expression == "rate(1 day)" && length(aws_lambda_permission.discovery_from_schedule) == 1
    error_message = "A daily rule and the permission for EventBridge to invoke discovery."
  }
}

run "a_cron_schedule_starts_pulls_with_the_batch_size" {
  command = plan
  module { source = "./backend" }
  variables {
    discovery_enabled             = true
    discovery_schedule_enabled    = true
    discovery_schedule_expression = "cron(0 0,12 * * ? *)"
  }
  assert {
    condition     = aws_cloudwatch_event_rule.discovery[0].schedule_expression == "cron(0 0,12 * * ? *)" && jsondecode(aws_cloudwatch_event_target.discovery[0].input).max_new == 10
    error_message = "The schedule is a variable, and each scheduled pull asks for the configured batch size."
  }
}

run "the_boards_can_be_changed" {
  command = plan
  module { source = "./backend" }
  variables {
    discovery_enabled           = true
    discovery_greenhouse_boards = ["airbnb"]
    discovery_max_new           = 25
  }
  assert {
    condition     = aws_lambda_function.discovery[0].environment[0].variables["GREENHOUSE_BOARDS"] == "airbnb" && aws_lambda_function.discovery[0].environment[0].variables["DISCOVERY_MAX_NEW"] == "25"
    error_message = "Boards and batch size are variables."
  }
}

run "adzuna_keywords_turn_adzuna_on" {
  command = plan
  module { source = "./backend" }
  variables {
    discovery_enabled         = true
    discovery_adzuna_searches = ["data engineer", "analyst"]
  }
  assert {
    condition     = aws_lambda_function.discovery[0].environment[0].variables["ADZUNA_SEARCHES"] == "data engineer,analyst"
    error_message = "The Adzuna keywords reach the function; the keys still come from the release."
  }
}
