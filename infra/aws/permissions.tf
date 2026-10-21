# Release SDK actions verified with IAM Policy Autopilot. ECR push permissions
# additionally cover Docker registry operations (not visible to an SDK scanner);
# Buildx reads the manifest (BatchGetImage) while pushing.
resource "aws_iam_role_policy" "release" {
  role = aws_iam_role.release.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    # Amplify authorizes these against the branch's deployment/job sub-resources
    # (CreateDeployment was denied on .../branches/main/deployments/*).
    { Effect = "Allow", Action = ["amplify:CreateDeployment", "amplify:StartDeployment", "amplify:GetJob"], Resource = [
      "${aws_amplify_app.web.arn}/branches/main",
      "${aws_amplify_app.web.arn}/branches/main/deployments/*",
      "${aws_amplify_app.web.arn}/branches/main/jobs/*",
    ] },
    { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
    { Effect = "Allow", Action = ["ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage", "ecr:BatchGetImage"], Resource = [aws_ecr_repository.api.arn, aws_ecr_repository.embed.arn] }
  ] })
}
resource "aws_iam_role_policy" "release_backend" {
  count = var.enable_backend ? 1 : 0
  role  = aws_iam_role.release.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["lambda:GetFunction", "lambda:GetFunctionConfiguration", "lambda:ListTags", "lambda:UpdateFunctionCode", "lambda:UpdateFunctionConfiguration"],
    Resource = compact([module.backend[0].api_arn, module.backend[0].migration_arn, module.backend[0].embed_arn]) },
    { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = module.backend[0].database_credentials_arn },
    { Effect = "Allow", Action = ["lambda:InvokeFunction"], Resource = module.backend[0].migration_arn },
    { Effect = "Allow", Action = ["lambda:PutFunctionConcurrency"], Resource = compact([module.backend[0].api_arn, module.backend[0].embed_arn]) }
  ] })
}
