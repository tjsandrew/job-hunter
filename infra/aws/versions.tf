terraform {
  required_version = ">= 1.10, < 2.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}

provider "aws" {
  region              = "ap-southeast-1"
  allowed_account_ids = [var.account_id]
  default_tags {
    tags = { Project = "jobhunter", Environment = "staging", ManagedBy = "Terraform" }
  }
}

variable "account_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "Set the intended 12-digit AWS account ID explicitly."
  }
}
variable "github_oidc_subject_prefix" {
  description = "This repo's OIDC sub prefix. It uses GitHub's immutable owner@id/repo@id form; check with: gh api repos/OWNER/REPO/actions/oidc/customization/sub"
  type        = string
  default     = "repo:tjsandrew@33519460/job-hunter@1404602000"
}
variable "github_oidc_provider_arn" {
  description = "Set this to reuse an existing GitHub OIDC provider in the account."
  type        = string
  default     = ""
}
variable "enable_backend" {
  description = "Opt in to the paid database/network/API stack after reviewing cost and the plan."
  type        = bool
  default     = false
}
variable "api_image_uri" {
  description = "Immutable ECR image digest from the initial build, required when enabling the backend."
  type        = string
  default     = ""
  validation {
    condition     = var.api_image_uri == "" || can(regex("@sha256:[a-f0-9]{64}$", var.api_image_uri))
    error_message = "Use an immutable ECR image digest, not a mutable tag."
  }
}

variable "activity_alert_emails" {
  description = "SNS recipients for the notification-only Aurora activity alarm; empty uses budget_alert_emails. Recipients must confirm their SNS email subscriptions."
  type        = set(string)
  default     = []
}
