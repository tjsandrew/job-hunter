# Runtime receives credentials at deployment; it cannot retrieve credential secrets.
locals { runtime_actions = jsondecode(file("${path.module}/runtime-actions.json")) }
resource "aws_iam_role_policy" "api" {
  role = aws_iam_role.api.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = local.runtime_actions.objects, Resource = ["${aws_s3_bucket.documents.arn}/uploads/*", "${aws_s3_bucket.documents.arn}/exports/*"] },
    { Effect = "Allow", Action = local.runtime_actions.versions, Resource = aws_s3_bucket.documents.arn,
    Condition = { StringLike = { "s3:prefix" = ["uploads/*", "exports/*"] } } }
  ] })
}
