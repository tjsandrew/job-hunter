# Mocked plans only: no AWS requests or resource creation.
# Checks the fit-analysis worker (docs/design/12-FIT-ANALYSIS.md): off by default, outside the VPC, narrow S3 access.
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
    condition     = length(aws_lambda_function.fit) == 0 && length(aws_lambda_permission.fit_from_s3) == 0 && length(aws_s3_bucket_notification.embed) == 0
    error_message = "Without fit_worker_enabled there is no fit function, no invoke permission and no bucket notification."
  }
  assert {
    condition     = aws_lambda_function.api.environment[0].variables["FIT_BACKEND"] == "inline"
    error_message = "The API must not write fit requests while the worker does not exist."
  }
}

run "the_worker_runs_outside_the_vpc_with_a_bounded_budget" {
  command = plan
  module { source = "./backend" }
  variables {
    fit_worker_enabled = true
  }
  assert {
    condition     = length(aws_lambda_function.fit[0].vpc_config) == 0
    error_message = "The fit worker must run outside the VPC: it has to reach the model gateway on the internet and must not reach the database."
  }
  assert {
    condition     = aws_lambda_function.fit[0].reserved_concurrent_executions == 3 && contains(aws_lambda_function.fit[0].architectures, "arm64")
    error_message = "At most three analyses run at once, on arm64."
  }
  assert {
    condition     = !contains(keys(aws_lambda_function.fit[0].environment[0].variables), "LLM_API_KEY")
    error_message = "The key must not be in Terraform state: the release workflow sets it from a GitHub secret."
  }
  assert {
    condition     = aws_lambda_function.api.environment[0].variables["FIT_BACKEND"] == "s3"
    error_message = "With the worker enabled the API hands requests to it through S3."
  }
  assert {
    condition     = length(aws_s3_bucket_notification.embed) == 1 && length(aws_s3_bucket_notification.embed[0].lambda_function) == 1 && aws_s3_bucket_notification.embed[0].lambda_function[0].filter_prefix == "fit-requests/"
    error_message = "Only request files wake the worker; its own result files must not."
  }
  assert {
    condition     = anytrue([for rule in aws_s3_bucket_lifecycle_configuration.embed_flags.rule : rule.id == "expire-fit-requests" && rule.expiration[0].days == 1]) && anytrue([for rule in aws_s3_bucket_lifecycle_configuration.embed_flags.rule : rule.id == "expire-fit-results" && rule.expiration[0].days == 1])
    error_message = "Request and result files hold profile text and must expire after a day."
  }
}
