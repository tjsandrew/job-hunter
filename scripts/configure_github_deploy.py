"""Publish NON-SECRET Terraform outputs as GitHub repository variables.

Run after reviewing/applying infra: terraform -chdir=infra/aws output -json
deployment | python3 scripts/configure_github_deploy.py
"""
import json
import subprocess
import sys

allowed = {"AWS_ROLE_ARN", "AWS_REGION", "AMPLIFY_APP_ID", "ECR_REPOSITORY", "API_FUNCTION", "MIGRATION_FUNCTION",
           "VITE_AUTH_MODE", "VITE_COGNITO_ISSUER", "VITE_COGNITO_CLIENT_ID", "VITE_COGNITO_DOMAIN", "VITE_API_SCOPE", "VITE_API_BASE_URL"}
values = json.load(sys.stdin)
if set(values) != allowed or not all(isinstance(value, str) for value in values.values()):
    raise SystemExit("Unexpected deployment output; no variables changed")
for name, value in values.items():
    subprocess.run(["gh", "variable", "set", name, "--repo", "tjsandrew/job-hunter", "--body", value], check=True)
    print("Configured " + name)
