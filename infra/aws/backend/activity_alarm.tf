variable "activity_alert_emails" { type = set(string) }

locals {
  activity_alarm_name = "${var.name}-aurora-active-hours"
  activity_alarm_arn  = "arn:aws:cloudwatch:ap-southeast-1:${var.account_id}:alarm:${local.activity_alarm_name}"
}

resource "aws_sns_topic" "activity" { name = "${var.name}-aurora-activity" }
resource "aws_sns_topic_subscription" "activity_email" {
  for_each  = var.activity_alert_emails
  topic_arn = aws_sns_topic.activity.arn
  protocol  = "email"
  endpoint  = each.value
}
resource "aws_sns_topic_policy" "activity" {
  arn = aws_sns_topic.activity.arn
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "cloudwatch.amazonaws.com" }, Action = "sns:Publish", Resource = aws_sns_topic.activity.arn
    Condition = {
      StringEquals = { "aws:SourceAccount" = var.account_id }
      ArnEquals    = { "aws:SourceArn" = concat([local.activity_alarm_arn], local.embed_alarm_arns) }
    }
  }] })
}

resource "aws_cloudwatch_metric_alarm" "activity" {
  alarm_name          = local.activity_alarm_name
  alarm_description   = "Notify the team when Aurora capacity remains above zero in every reported sample for at least 18 of the last 24 hourly periods. Notification only; no automatic shutdown."
  namespace           = "AWS/RDS"
  metric_name         = "ServerlessDatabaseCapacity"
  dimensions          = { DBInstanceIdentifier = aws_rds_cluster_instance.writer.identifier }
  statistic           = "Minimum"
  period              = 3600
  evaluation_periods  = 24
  datapoints_to_alarm = 18
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.activity.arn]
  # No OK or daily-repeat email actions. Email subscriptions require acceptance.
  depends_on = [aws_sns_topic_policy.activity]
  lifecycle {
    precondition {
      condition     = length(var.activity_alert_emails) > 0
      error_message = "Configure activity_alert_emails or budget_alert_emails before enabling the paid backend."
    }
  }
}

output "activity_monitoring" {
  value = { alarm_name = aws_cloudwatch_metric_alarm.activity.alarm_name, sns_topic_arn = aws_sns_topic.activity.arn }
}
