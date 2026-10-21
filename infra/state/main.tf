terraform {
  required_version = ">= 1.10, < 2.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
  # First bootstrap uses the temporary, ignored bootstrap_override.tf to select
  # local state. Remove it and migrate this state to S3 after bucket creation.
  backend "s3" {}
}

variable "account_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "Set the intended 12-digit AWS account ID explicitly."
  }
}

provider "aws" {
  region              = "ap-southeast-1"
  allowed_account_ids = [var.account_id]
  default_tags {
    tags = { Project = "jobhunter", Environment = "staging", ManagedBy = "Terraform", Purpose = "terraform-state" }
  }
}

resource "aws_s3_bucket" "state" {
  bucket        = "jobhunter-${var.account_id}-tfstate"
  force_destroy = false
  # The state bucket outlives app teardown. Review removal of this protection
  # only after all application resources and retained backups are accounted for.
  lifecycle { prevent_destroy = true }
}
resource "aws_s3_bucket_ownership_controls" "state" {
  bucket = aws_s3_bucket.state.id
  rule { object_ownership = "BucketOwnerEnforced" }
}
resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}
resource "aws_s3_bucket_policy" "state_tls" {
  bucket = aws_s3_bucket.state.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Sid       = "DenyInsecureTransport"
    Effect    = "Deny"
    Principal = "*"
    Action    = "s3:*"
    Resource  = [aws_s3_bucket.state.arn, "${aws_s3_bucket.state.arn}/*"]
    Condition = { Bool = { "aws:SecureTransport" = "false" } }
  }] })
}

output "bucket_name" { value = aws_s3_bucket.state.bucket }
output "region" { value = "ap-southeast-1" }
