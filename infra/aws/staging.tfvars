# Shared staging settings: no passwords, tokens or AWS credentials.
# Include with -var-file=staging.tfvars for every staging plan.
account_id            = "091512051916"
budget_alert_emails   = ["jsandrewtiong@gmail.com"]
activity_alert_emails = ["jsandrewtiong@gmail.com"]
monthly_budget_usd    = 40
enable_backend        = true
api_image_uri         = "091512051916.dkr.ecr.ap-southeast-1.amazonaws.com/jobhunter-staging@sha256:3c45fd7770878fd58f1c5f912de55c520e9596d3e188a165b877e0085fd55072"
