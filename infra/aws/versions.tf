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

variable "embed_image_uri" {
  description = "Immutable ECR digest of the embed worker image (docs/design/11-EMBEDDING-WORKER.md). Empty creates only the stage-1 resources: queue, dead-letter queue, IAM, alarm and the ECR repository."
  type        = string
  default     = ""
  validation {
    condition     = var.embed_image_uri == "" || can(regex("@sha256:[a-f0-9]{64}$", var.embed_image_uri))
    error_message = "Use an immutable ECR image digest, not a mutable tag."
  }
}
variable "fit_worker_enabled" {
  description = "Create the fit-analysis worker (design brief 12) and switch the API to hand fit requests to it through S3. The SoCLaaS key comes from the GitHub secret LLM_API_KEY at release time. Needs the course staff's agreement that a deployed app may use one key."
  type        = bool
  default     = false
}
variable "embed_on_save" {
  description = "0 (off) or queue (the API writes the S3 flag after a profile save). Set queue only once the embed worker is live."
  type        = string
  default     = "0"
  validation {
    condition     = contains(["0", "queue"], var.embed_on_save)
    error_message = "embed_on_save must be 0 or queue."
  }
}
variable "for_you_enabled" {
  description = "1 serves the semantic For you list (GET /v1/recommendations/for-you); 0 answers 404 FOR_YOU_DISABLED and the web app hides the toggle. Needs embed_on_save = queue, or no profile vector is ever produced."
  type        = string
  default     = "0"
  validation {
    condition     = contains(["0", "1"], var.for_you_enabled)
    error_message = "for_you_enabled must be 0 or 1."
  }
}

variable "activity_alert_emails" {
  description = "SNS recipients for the notification-only Aurora activity alarm; empty uses budget_alert_emails. Recipients must confirm their SNS email subscriptions."
  type        = set(string)
  default     = []
}
