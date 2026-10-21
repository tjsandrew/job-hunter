# Mocked plan only; never creates the bucket or reads a real backend.
mock_provider "aws" {}

run "private_recoverable_state" {
  command = plan
  variables { account_id = "123456789012" }
  assert {
    condition     = aws_s3_bucket_public_access_block.state.block_public_acls && aws_s3_bucket_public_access_block.state.block_public_policy && aws_s3_bucket_public_access_block.state.ignore_public_acls && aws_s3_bucket_public_access_block.state.restrict_public_buckets
    error_message = "Terraform state must not be public."
  }
  assert {
    condition     = aws_s3_bucket_versioning.state.versioning_configuration[0].status == "Enabled" && !aws_s3_bucket.state.force_destroy
    error_message = "State must retain recoverable versions and refuse automatic object deletion."
  }
  assert {
    condition     = one(one(aws_s3_bucket_server_side_encryption_configuration.state.rule).apply_server_side_encryption_by_default).sse_algorithm == "AES256"
    error_message = "State must use server-side encryption."
  }
}
