terraform {
  required_providers {
    aws = { source = "hashicorp/aws" }
  }
}
variable "name" { type = string }
variable "account_id" { type = string }
variable "origin" { type = string }
variable "cognito_issuer" { type = string }
variable "client_id" { type = string }
variable "image_uri" {
  type = string
  validation {
    condition     = can(regex("@sha256:[a-f0-9]{64}$", var.image_uri))
    error_message = "Build and push the initial image before enabling the backend."
  }
}
data "aws_availability_zones" "available" { state = "available" }
resource "aws_vpc" "app" {
  cidr_block           = "10.52.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true
}
resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.app.id
  cidr_block        = "10.52.${count.index}.0/24"
  availability_zone = data.aws_availability_zones.available.names[count.index]
}
resource "aws_route_table" "private" { vpc_id = aws_vpc.app.id }
resource "aws_route_table_association" "private" {
  count          = 2
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}
resource "aws_security_group" "lambda" {
  name   = "${var.name}-lambda"
  vpc_id = aws_vpc.app.id
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
resource "aws_security_group" "database" {
  name   = "${var.name}-database"
  vpc_id = aws_vpc.app.id
  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.lambda.id]
  }
}
# No NAT gateway: this milestone makes no internet/model calls from the API.
resource "aws_vpc_endpoint" "s3" {
  vpc_id          = aws_vpc.app.id
  service_name    = "com.amazonaws.ap-southeast-1.s3"
  route_table_ids = [aws_route_table.private.id]
}
resource "aws_db_subnet_group" "app" {
  name       = var.name
  subnet_ids = aws_subnet.private[*].id
}
# PostgreSQL-compatible serverless compute; the cluster remains private.
resource "aws_rds_cluster" "app" {
  cluster_identifier                  = var.name
  engine                              = "aurora-postgresql"
  engine_mode                         = "provisioned"
  engine_version                      = "16.15"
  database_name                       = "jobhunter"
  master_username                     = "jobhunter_admin"
  manage_master_user_password         = true
  iam_database_authentication_enabled = false
  storage_encrypted                   = true
  storage_type                        = "aurora"
  db_subnet_group_name                = aws_db_subnet_group.app.name
  vpc_security_group_ids              = [aws_security_group.database.id]
  backup_retention_period             = 7
  deletion_protection                 = true
  skip_final_snapshot                 = false
  final_snapshot_identifier           = "${var.name}-final"
  serverlessv2_scaling_configuration {
    min_capacity             = 0
    max_capacity             = 1
    seconds_until_auto_pause = 1800
  }
  # Do not try to downgrade a minor version applied by AWS maintenance.
  # Deliberate engine upgrades require reviewing/removing this ignore rule.
  lifecycle { ignore_changes = [engine_version] }
}
resource "aws_rds_cluster_instance" "writer" {
  identifier                 = "${var.name}-writer"
  cluster_identifier         = aws_rds_cluster.app.id
  instance_class             = "db.serverless"
  engine                     = aws_rds_cluster.app.engine
  publicly_accessible        = false
  auto_minor_version_upgrade = true
  db_subnet_group_name       = aws_db_subnet_group.app.name
}
resource "aws_s3_bucket" "documents" { bucket = "${var.name}-${var.account_id}-documents" }
resource "aws_s3_bucket_public_access_block" "documents" {
  bucket                  = aws_s3_bucket.documents.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_versioning" "documents" {
  bucket = aws_s3_bucket.documents.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}
resource "aws_s3_bucket_cors_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id
  cors_rule {
    allowed_origins = [var.origin]
    allowed_methods = ["PUT", "GET", "HEAD"]
    allowed_headers = ["content-type"]
    expose_headers  = ["ETag"]
    max_age_seconds = 300
  }
}
resource "aws_iam_role" "api" {
  name = "${var.name}-api"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole"
  }] })
}
resource "aws_iam_role" "migrate" {
  name               = "${var.name}-migrate"
  assume_role_policy = aws_iam_role.api.assume_role_policy
}
resource "aws_iam_role_policy_attachment" "network" {
  for_each   = { api = aws_iam_role.api.name, migrate = aws_iam_role.migrate.name }
  role       = each.value
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}
resource "aws_cloudwatch_log_group" "lambda" {
  for_each          = toset(["api", "migrate"])
  name              = "/aws/lambda/${var.name}-${each.key}"
  retention_in_days = 7
}
resource "aws_lambda_function" "api" {
  function_name                  = "${var.name}-api"
  role                           = aws_iam_role.api.arn
  package_type                   = "Image"
  image_uri                      = var.image_uri
  architectures                  = ["arm64"]
  memory_size                    = 1024
  timeout                        = 29
  reserved_concurrent_executions = 10
  vpc_config {
    subnet_ids         = aws_subnet.private[*].id
    security_group_ids = [aws_security_group.lambda.id]
  }
  environment {
    variables = {
      APP_ENV         = "aws", AUTH_MODE = "cognito", STORAGE_BACKEND = "s3"
      DATABASE_AUTH   = "password", DATABASE_USERNAME = "jobhunter_app"
      DATABASE_HOST   = aws_rds_cluster.app.endpoint, DATABASE_NAME = aws_rds_cluster.app.database_name
      DB_POOL_SIZE    = "1", PDF_STORAGE_DIR = "/tmp/exports", AUTO_CREATE_SCHEMA = "false"
      DOCUMENT_BUCKET = aws_s3_bucket.documents.id, CORS_ORIGINS = var.origin
      COGNITO_ISSUER  = var.cognito_issuer, COGNITO_CLIENT_ID = var.client_id
      API_SCOPE       = "jobhunter/use", MODEL_BACKEND = "heuristic", FOR_YOU_ENABLED = var.for_you_enabled, EMBED_ON_SAVE = var.embed_on_save
      LLM_WORKER      = var.llm_worker_enabled ? "s3" : "inline"
    }
  }
  # Manual controls own concurrency after creation; infrastructure updates must
  # not silently undo a pause. A fresh function starts with the limit above.
  lifecycle { ignore_changes = [image_uri, reserved_concurrent_executions, environment[0].variables["DATABASE_PASSWORD"]] }
  depends_on = [aws_iam_role_policy_attachment.network, aws_cloudwatch_log_group.lambda, aws_rds_cluster_instance.writer, aws_iam_role_policy.api]
}
resource "aws_lambda_function" "migrate" {
  function_name = "${var.name}-migrate"
  role          = aws_iam_role.migrate.arn
  package_type  = "Image"
  image_uri     = var.image_uri
  architectures = ["arm64"]
  image_config { command = ["job_hunter.migrate_aws.handler"] }
  memory_size                    = 512
  timeout                        = 300
  reserved_concurrent_executions = 1
  vpc_config {
    subnet_ids         = aws_subnet.private[*].id
    security_group_ids = [aws_security_group.lambda.id]
  }
  environment {
    variables = {
      DATABASE_AUTH = "password", DATABASE_USERNAME = "jobhunter_migrator"
      DATABASE_HOST = aws_rds_cluster.app.endpoint, DATABASE_NAME = aws_rds_cluster.app.database_name
    }
  }
  lifecycle { ignore_changes = [image_uri, environment[0].variables["DATABASE_PASSWORD"]] }
  depends_on = [aws_iam_role_policy_attachment.network, aws_cloudwatch_log_group.lambda, aws_rds_cluster_instance.writer, aws_iam_role_policy.api]
}
resource "aws_apigatewayv2_api" "app" {
  name          = var.name
  protocol_type = "HTTP"
  # Gateway owns browser CORS, including responses generated before Lambda.
  # It ignores backend CORS headers when this configuration is present.
  cors_configuration {
    allow_origins = [var.origin]
    allow_methods = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    allow_headers = ["authorization", "content-type"]
    max_age       = 300
  }
}
resource "aws_apigatewayv2_authorizer" "users" {
  api_id           = aws_apigatewayv2_api.app.id
  name             = "cognito"
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  jwt_configuration {
    audience = [var.client_id]
    issuer   = var.cognito_issuer
  }
}
resource "aws_apigatewayv2_integration" "api" {
  api_id                 = aws_apigatewayv2_api.app.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = 30000
}
resource "aws_apigatewayv2_route" "private" {
  api_id               = aws_apigatewayv2_api.app.id
  route_key            = "$default"
  target               = "integrations/${aws_apigatewayv2_integration.api.id}"
  authorization_type   = "JWT"
  authorizer_id        = aws_apigatewayv2_authorizer.users.id
  authorization_scopes = ["jobhunter/use"]
}
resource "aws_apigatewayv2_route" "public" {
  for_each  = toset(["GET /v1/health", "OPTIONS /{proxy+}"])
  api_id    = aws_apigatewayv2_api.app.id
  route_key = each.value
  target    = "integrations/${aws_apigatewayv2_integration.api.id}"
}
resource "aws_apigatewayv2_stage" "app" {
  api_id      = aws_apigatewayv2_api.app.id
  name        = "$default"
  auto_deploy = true
  default_route_settings {
    throttling_burst_limit = 40
    throttling_rate_limit  = 20
  }
  route_settings {
    route_key              = aws_apigatewayv2_route.public["GET /v1/health"].route_key
    throttling_burst_limit = 2
    throttling_rate_limit  = 1
  }
}
resource "aws_lambda_permission" "gateway" {
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.api.function_name
  principal      = "apigateway.amazonaws.com"
  source_arn     = "${aws_apigatewayv2_api.app.execution_arn}/*/*"
  source_account = var.account_id
}
output "api_url" { value = aws_apigatewayv2_api.app.api_endpoint }
output "api_function" { value = aws_lambda_function.api.function_name }
output "migration_function" { value = aws_lambda_function.migrate.function_name }
output "api_arn" { value = aws_lambda_function.api.arn }
output "migration_arn" { value = aws_lambda_function.migrate.arn }

output "bootstrap" {
  value = { function_name = aws_lambda_function.migrate.function_name, master_secret_arn = aws_rds_cluster.app.master_user_secret[0].secret_arn }
}

# Metadata only: the operator bootstrap writes credential values outside Terraform.
resource "aws_secretsmanager_secret" "database_credentials" {
  name        = "${var.name}-database-credentials"
  description = "Deployment-injected application and migrator database passwords"
}
output "database_credentials_arn" { value = aws_secretsmanager_secret.database_credentials.arn }
