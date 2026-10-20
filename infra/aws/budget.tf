variable "budget_alert_emails" {
  description = "Team addresses for cost alerts. Keep them in an untracked tfvars file; empty skips the budget."
  type        = list(string)
  default     = []
}
variable "monthly_budget_usd" {
  description = "Monthly account spend that triggers alerts. Alerts only notify; they never stop resources."
  type        = number
  default     = 40
}

# Account-wide rather than tag-filtered: cost-allocation tags are not activated,
# and stray resources outside Terraform should alert too.
resource "aws_budgets_budget" "monthly" {
  count        = length(var.budget_alert_emails) > 0 ? 1 : 0
  name         = "${local.name}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"
  # Credits would net spend to zero and silence every alert.
  cost_types {
    include_credit = false
    include_refund = false
  }
  dynamic "notification" {
    # Two actual-spend notices per monthly period; no forecast fluctuation emails.
    for_each = { actual-80 = ["ACTUAL", 80], actual-100 = ["ACTUAL", 100] }
    content {
      comparison_operator        = "GREATER_THAN"
      notification_type          = notification.value[0]
      threshold                  = notification.value[1]
      threshold_type             = "PERCENTAGE"
      subscriber_email_addresses = var.budget_alert_emails
    }
  }
}
