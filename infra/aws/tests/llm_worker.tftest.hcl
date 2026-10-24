# Mocked plans only: no AWS requests or resource creation.
# Checks the shared LLM worker (docs/design/12-FIT-ANALYSIS.md): off by default, outside the VPC, narrow S3 access.
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

run "the_worker_is_off_by_default_and_the_api_keeps_the_local_mode" {
  command = plan
  module { source = "./backend" }
  assert {
    condition     = length(aws_lambda_function.llm) == 0 && length(aws_lambda_permission.llm_from_s3) == 0 && length(aws_s3_bucket_notification.embed) == 0
    error_message = "Without llm_worker_enabled there is no LLM function, no invoke permission and no bucket notification."
  }
  assert {
    condition     = aws_lambda_function.api.environment[0].variables["LLM_WORKER"] == "inline"
    error_message = "The API must not write LLM requests while the worker does not exist."
  }
}

run "the_worker_runs_outside_the_vpc_with_a_bounded_budget" {
  command = plan
  module { source = "./backend" }
  variables {
    llm_worker_enabled = true
  }
  assert {
    condition     = length(aws_lambda_function.llm[0].vpc_config) == 0
    error_message = "The LLM worker must run outside the VPC: it has to reach the model gateway on the internet and must not reach the database."
  }
  assert {
    condition     = aws_lambda_function.llm[0].reserved_concurrent_executions == 5 && contains(aws_lambda_function.llm[0].architectures, "arm64")
    error_message = "By default at most five requests run at once, on arm64."
  }
  assert {
    condition     = aws_lambda_function.llm[0].function_name == "test-staging-llm" && aws_lambda_function.llm[0].image_config[0].command[0] == "job_hunter.llm_worker.handler"
    error_message = "The function is the shared LLM worker, not a feature-specific one."
  }
  assert {
    condition     = !contains(keys(aws_lambda_function.llm[0].environment[0].variables), "LLM_API_KEY")
    error_message = "The key must not be in Terraform state: the release workflow sets it from a GitHub secret."
  }
  assert {
    condition     = aws_lambda_function.api.environment[0].variables["LLM_WORKER"] == "s3"
    error_message = "With the worker enabled the API hands requests to it through S3."
  }
  assert {
    condition     = length(aws_s3_bucket_notification.embed) == 1 && length(aws_s3_bucket_notification.embed[0].lambda_function) == 1 && aws_s3_bucket_notification.embed[0].lambda_function[0].filter_prefix == "llm-requests/"
    error_message = "Only request files wake the worker; its own result files must not."
  }
  assert {
    condition     = alltrue([for prefix in ["llm-requests", "llm-results", "fit-requests", "fit-results"] : anytrue([for rule in aws_s3_bucket_lifecycle_configuration.embed_flags.rule : rule.id == "expire-${prefix}" && rule.expiration[0].days == 1])])
    error_message = "Request and result files hold profile and resume text and must expire after a day, including the first version's fit-* prefixes."
  }
}

run "the_concurrency_limit_can_be_changed" {
  command = plan
  module { source = "./backend" }
  variables {
    llm_worker_enabled  = true
    llm_max_concurrency = 8
  }
  assert {
    condition     = aws_lambda_function.llm[0].reserved_concurrent_executions == 8
    error_message = "llm_max_concurrency sets the worker's reserved concurrency."
  }
}
