# Mocked plans only: no AWS requests or resource creation.
mock_provider "aws" {
  mock_data "aws_availability_zones" {
    defaults = { names = ["ap-southeast-1a", "ap-southeast-1b"] }
  }
}

run "team_only_foundation" {
  command = plan
  variables { account_id = "123456789012" }
  assert {
    condition     = aws_cognito_user_pool.users.admin_create_user_config[0].allow_admin_create_user_only && length(aws_cognito_user_pool_client.web.supported_identity_providers) == 1 && contains(aws_cognito_user_pool_client.web.supported_identity_providers, "COGNITO")
    error_message = "The approved foundation is team-only and uses Cognito email login without social providers."
  }
}

run "guarded_aurora" {
  command = plan
  module { source = "./backend" }
  variables {
    name                  = "test-staging"
    account_id            = "123456789012"
    origin                = "https://main.example.amplifyapp.com"
    cognito_issuer        = "https://cognito-idp.ap-southeast-1.amazonaws.com/example"
    client_id             = "test-client"
    image_uri             = "123456789012.dkr.ecr.ap-southeast-1.amazonaws.com/test@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    activity_alert_emails = ["team@example.test"]
  }
  assert {
    condition     = aws_rds_cluster.app.serverlessv2_scaling_configuration[0].min_capacity == 0 && aws_rds_cluster.app.serverlessv2_scaling_configuration[0].max_capacity == 1
    error_message = "Staging must retain auto-pause and the lowest supported 1 ACU maximum."
  }
  assert {
    condition     = aws_cloudwatch_metric_alarm.activity.period == 3600 && aws_cloudwatch_metric_alarm.activity.evaluation_periods == 24 && aws_cloudwatch_metric_alarm.activity.datapoints_to_alarm == 18 && aws_cloudwatch_metric_alarm.activity.statistic == "Minimum" && aws_cloudwatch_metric_alarm.activity.threshold == 0 && aws_cloudwatch_metric_alarm.activity.comparison_operator == "GreaterThanThreshold" && aws_cloudwatch_metric_alarm.activity.treat_missing_data == "notBreaching"
    error_message = "The activity guard must use 18 of 24 hourly minima above zero, without treating paused/missing periods as activity."
  }
  assert {
    condition     = anytrue([for route in aws_apigatewayv2_stage.app.route_settings : route.route_key == "GET /v1/health" && route.throttling_rate_limit == 1 && route.throttling_burst_limit == 2])
    error_message = "The public health route must retain its separate 1/second, burst-2 throttle."
  }

}

run "reject_missing_recipients" {
  command = plan
  module { source = "./backend" }
  variables {
    name                  = "test-staging"
    account_id            = "123456789012"
    origin                = "https://main.example.amplifyapp.com"
    cognito_issuer        = "https://cognito-idp.ap-southeast-1.amazonaws.com/example"
    client_id             = "test-client"
    image_uri             = "123456789012.dkr.ecr.ap-southeast-1.amazonaws.com/test@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    activity_alert_emails = []
  }
  expect_failures = [aws_cloudwatch_metric_alarm.activity]
}
