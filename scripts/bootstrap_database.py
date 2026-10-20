"""One-time operator setup; no password file, command argument or Terraform value.

AWS_PROFILE=nus python scripts/bootstrap_database.py --function <migration-function> --secret-arn <master-secret-arn>
"""
import argparse
import json

import boto3
from botocore.config import Config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--function", required=True)
    parser.add_argument("--secret-arn", required=True)
    args = parser.parse_args()
    client = boto3.client("lambda", config=Config(read_timeout=330, connect_timeout=10, retries={"total_max_attempts": 1}))
    def invoke(event):
        result = client.invoke(FunctionName=args.function, InvocationType="RequestResponse", Payload=json.dumps(event).encode())
        body = json.loads(result["Payload"].read())
        return None if result.get("FunctionError") else body.get("status")
    # rds_iam takes precedence over password auth after initial setup.
    if invoke({"action": "check"}) == "ready":
        print("IAM login is configured; run the normal migration release.")
        return
    credentials = json.loads(boto3.client("secretsmanager").get_secret_value(SecretId=args.secret_arn)["SecretString"])
    if invoke({"action": "bootstrap", "credentials": credentials}) != "migrated":
        raise SystemExit("Bootstrap failed; inspect migration logs. No credentials were printed.")
    print("IAM roles and schema initialized. Verify a normal IAM migration before releasing the API.")


if __name__ == "__main__":
    main()
