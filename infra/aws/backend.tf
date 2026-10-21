terraform {
  # Configure with -backend-config=backend.hcl after the state-bucket bootstrap.
  # CI uses init -backend=false; do not put AWS credentials in this block.
  backend "s3" {}
}
