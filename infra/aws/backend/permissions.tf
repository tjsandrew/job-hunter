# Action names are reviewed/narrowed from AWS IAM Policy Autopilot's SDK scan.
# Scope those generated groups to this deployment's bucket. IAM DB tokens are
# signed locally; rds-db:connect is scoped by cluster RESOURCE ID and SQL role:
# https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/UsingWithRDS.IAMDBAuth.IAMPolicy.html
locals { runtime_actions = jsondecode(file("${path.module}/runtime-actions.json")) }
resource "aws_iam_role_policy" "api" {
  role = aws_iam_role.api.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = local.runtime_actions.objects, Resource = ["${aws_s3_bucket.documents.arn}/uploads/*", "${aws_s3_bucket.documents.arn}/exports/*"] },
    { Effect = "Allow", Action = local.runtime_actions.versions, Resource = aws_s3_bucket.documents.arn,
    Condition = { StringLike = { "s3:prefix" = ["uploads/*", "exports/*"] } } },
    { Effect = "Allow", Action = ["rds-db:connect"], Resource = "arn:aws:rds-db:ap-southeast-1:${var.account_id}:dbuser:${aws_rds_cluster.app.cluster_resource_id}/jobhunter_app" }
  ] })
}
resource "aws_iam_role_policy" "migrate" {
  role = aws_iam_role.migrate.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["rds-db:connect"], Resource = "arn:aws:rds-db:ap-southeast-1:${var.account_id}:dbuser:${aws_rds_cluster.app.cluster_resource_id}/jobhunter_admin" }
  ] })
}
