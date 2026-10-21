# Existing shared state; authenticate separately through AWS SSO.
bucket              = "jobhunter-091512051916-tfstate"
key                 = "staging/terraform.tfstate"
region              = "ap-southeast-1"
encrypt             = true
use_lockfile        = true
allowed_account_ids = ["091512051916"]
