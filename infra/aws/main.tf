locals {
  name   = "jobhunter-staging"
  origin = "https://main.${aws_amplify_app.web.default_domain}"
}

# GitHub Actions uploads tested build artifacts; Amplify needs no GitHub token.
resource "aws_amplify_app" "web" {
  name     = local.name
  platform = "WEB"
  custom_rule {
    source = "</^[^.]+$|\\.(?!(css|gif|ico|jpg|jpeg|js|png|txt|svg|woff|woff2|ttf|map|json|webp)$)([^.]+$)/>"
    target = "/index.html"
    status = "200"
  }
  custom_headers = <<-HEADERS
    customHeaders:
      - pattern: '**'
        headers:
          - key: X-Content-Type-Options
            value: nosniff
          - key: Referrer-Policy
            value: strict-origin-when-cross-origin
          - key: X-Frame-Options
            value: DENY
          - key: Strict-Transport-Security
            value: max-age=31536000
  HEADERS
  # Amplify's UpdateApp accepts headers only as YAML with a top-level customHeaders key, but stores
  # and returns them as compact JSON, so Terraform would report a change on every plan. To change
  # headers: edit them here, merge, then apply once with a local override file that clears this
  # ignore (docs/deployment/README.md, "Changing the website's security headers").
  lifecycle { ignore_changes = [custom_headers] }
}
resource "aws_amplify_branch" "main" {
  app_id            = aws_amplify_app.web.id
  branch_name       = "main"
  stage             = "PRODUCTION"
  enable_auto_build = false
}

resource "aws_cognito_user_pool" "users" {
  name                     = local.name
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]
  deletion_protection      = "ACTIVE"
  user_pool_tier           = "LITE"
  # Team-only access: create ordinary Cognito accounts for teammates and demos.
  admin_create_user_config { allow_admin_create_user_only = true }
  password_policy {
    minimum_length    = 12
    require_lowercase = true
    require_uppercase = true
    require_numbers   = true
    require_symbols   = true
  }
  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }
}
resource "aws_cognito_resource_server" "api" {
  identifier   = "jobhunter"
  name         = "Job Hunter API"
  user_pool_id = aws_cognito_user_pool.users.id
  scope {
    scope_name        = "use"
    scope_description = "Use your personal Job Hunter workspace"
  }
}
resource "aws_cognito_user_pool_client" "web" {
  name                                 = "web"
  user_pool_id                         = aws_cognito_user_pool.users.id
  generate_secret                      = false
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile", "${aws_cognito_resource_server.api.identifier}/use"]
  supported_identity_providers         = ["COGNITO"]
  callback_urls                        = ["${local.origin}/auth/callback"]
  logout_urls                          = [local.origin]
  prevent_user_existence_errors        = "ENABLED"
  enable_token_revocation              = true
  access_token_validity                = 60
  id_token_validity                    = 60
  refresh_token_validity               = 1
  explicit_auth_flows                  = ["ALLOW_REFRESH_TOKEN_AUTH"]
  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }
}
resource "aws_cognito_user_pool_domain" "login" {
  domain                = "${local.name}-${var.account_id}"
  user_pool_id          = aws_cognito_user_pool.users.id
  managed_login_version = 1
}
resource "aws_ecr_repository" "api" {
  name                 = local.name
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration { scan_on_push = true }
}
# Release recovery only rolls back to the previously deployed image, which is
# always among the newest images kept here.
resource "aws_ecr_lifecycle_policy" "api" {
  repository = aws_ecr_repository.api.name
  policy = jsonencode({ rules = [{
    rulePriority = 1, description = "Keep the 15 newest images"
    selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 15 }
    action       = { type = "expire" }
  }] })
}

resource "aws_ecr_repository" "embed" {
  name                 = "${local.name}-embed"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration { scan_on_push = true }
}

module "backend" {
  source                = "./backend"
  count                 = var.enable_backend ? 1 : 0
  name                  = local.name
  account_id            = var.account_id
  origin                = local.origin
  cognito_issuer        = "https://${aws_cognito_user_pool.users.endpoint}"
  client_id             = aws_cognito_user_pool_client.web.id
  image_uri             = var.api_image_uri
  activity_alert_emails = length(var.activity_alert_emails) > 0 ? var.activity_alert_emails : toset(var.budget_alert_emails)
  embed_image_uri       = var.embed_image_uri
  embed_on_save         = var.embed_on_save
  for_you_enabled       = var.for_you_enabled
  llm_worker_enabled    = var.llm_worker_enabled

  discovery_enabled                  = var.discovery_enabled
  discovery_greenhouse_boards        = var.discovery_greenhouse_boards
  discovery_lever_boards             = var.discovery_lever_boards
  discovery_mycareersfuture_searches = var.discovery_mycareersfuture_searches
  discovery_adzuna_searches          = var.discovery_adzuna_searches
  discovery_max_new                  = var.discovery_max_new
  discovery_schedule_enabled         = var.discovery_schedule_enabled
  discovery_schedule_expression      = var.discovery_schedule_expression

  aurora_max_acu      = var.aurora_max_acu
  gateway_rate_limit  = var.gateway_rate_limit
  gateway_burst_limit = var.gateway_burst_limit
}

resource "aws_iam_openid_connect_provider" "github" {
  count          = var.github_oidc_provider_arn == "" ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}
resource "aws_iam_role" "release" {
  name = "${local.name}-github-release"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow", Action = "sts:AssumeRoleWithWebIdentity"
      Principal = { Federated = var.github_oidc_provider_arn != "" ? var.github_oidc_provider_arn : aws_iam_openid_connect_provider.github[0].arn }
      Condition = { StringEquals = {
        "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        "token.actions.githubusercontent.com:sub" = "${var.github_oidc_subject_prefix}:ref:refs/heads/main"
      } }
    }]
  })
}

output "website_url" { value = local.origin }
output "release_role_arn" { value = aws_iam_role.release.arn }
output "ecr_repository_url" { value = aws_ecr_repository.api.repository_url }
output "embed_ecr_repository_url" { value = aws_ecr_repository.embed.repository_url }
output "database_bootstrap" { value = try(module.backend[0].bootstrap, null) }
output "activity_monitoring" { value = try(module.backend[0].activity_monitoring, null) }
output "deployment" {
  value = {
    AWS_ROLE_ARN                    = aws_iam_role.release.arn
    AWS_REGION                      = "ap-southeast-1"
    AMPLIFY_APP_ID                  = aws_amplify_app.web.id
    ECR_REPOSITORY                  = aws_ecr_repository.api.repository_url
    DATABASE_CREDENTIALS_SECRET_ARN = try(module.backend[0].database_credentials_arn, "")
    API_FUNCTION                    = try(module.backend[0].api_function, "")
    MIGRATION_FUNCTION              = try(module.backend[0].migration_function, "")
    EMBED_ECR_REPOSITORY            = aws_ecr_repository.embed.repository_url
    EMBED_FUNCTION                  = try(module.backend[0].embed_function, "")
    LLM_FUNCTION                    = try(module.backend[0].llm_function, "")
    DISCOVERY_FUNCTION              = try(module.backend[0].discovery_function, "")
    IMPORT_FUNCTION                 = try(module.backend[0].import_function, "")
    VITE_AUTH_MODE                  = "cognito"
    VITE_COGNITO_ISSUER             = "https://${aws_cognito_user_pool.users.endpoint}"
    VITE_COGNITO_CLIENT_ID          = aws_cognito_user_pool_client.web.id
    VITE_COGNITO_DOMAIN             = "https://${aws_cognito_user_pool_domain.login.domain}.auth.ap-southeast-1.amazoncognito.com"
    VITE_API_SCOPE                  = "jobhunter/use"
    VITE_API_BASE_URL               = try("${module.backend[0].api_url}/v1", "")
  }
}
