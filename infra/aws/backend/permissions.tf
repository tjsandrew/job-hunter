# Runtime receives credentials at deployment; it cannot retrieve credential secrets.
locals { runtime_actions = jsondecode(file("${path.module}/runtime-actions.json")) }
resource "aws_iam_role_policy" "api" {
  role = aws_iam_role.api.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = local.runtime_actions.objects, Resource = ["${aws_s3_bucket.documents.arn}/uploads/*", "${aws_s3_bucket.documents.arn}/exports/*"] },
    { Effect = "Allow", Action = local.runtime_actions.versions, Resource = aws_s3_bucket.documents.arn,
    Condition = { StringLike = { "s3:prefix" = ["uploads/*", "exports/*"] } } },
    # The embed flag is write-only for the API: it can create flags but not read, list or delete anything under the prefix.
    { Effect = "Allow", Action = ["s3:PutObject"], Resource = "${aws_s3_bucket.documents.arn}/${local.embed_flag_prefix}*" },
    # LLM worker (fit analysis, resume rewrite): the API writes a request file and reads back its result. It cannot list or delete either.
    { Effect = "Allow", Action = ["s3:PutObject"], Resource = "${aws_s3_bucket.documents.arn}/${local.llm_request_prefix}*" },
    { Effect = "Allow", Action = ["s3:GetObject"], Resource = "${aws_s3_bucket.documents.arn}/${local.llm_result_prefix}*" }
  ] })
}
