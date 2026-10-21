"""Configure password roles using operator access; no secrets in argv or files."""
import argparse
import json
import secrets

import boto3
from botocore.config import Config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--function", required=True)
    parser.add_argument("--secret-arn", required=True, help="AWS-managed master secret")
    parser.add_argument("--credentials-secret-arn", required=True)
    args = parser.parse_args()
    client = boto3.client("lambda", config=Config(read_timeout=330, connect_timeout=10,
                                                   retries={"total_max_attempts": 1}))
    store = boto3.client("secretsmanager")
    # Persist first, then retry the same passwords if setup is interrupted.
    try:
        passwords = json.loads(store.get_secret_value(SecretId=args.credentials_secret_arn)["SecretString"])
    except store.exceptions.ResourceNotFoundException:
        passwords = {role: secrets.token_urlsafe(48) for role in ("jobhunter_app", "jobhunter_migrator")}
        store.put_secret_value(SecretId=args.credentials_secret_arn, SecretString=json.dumps(passwords))
    credentials = json.loads(store.get_secret_value(SecretId=args.secret_arn)["SecretString"])
    result = client.invoke(FunctionName=args.function, InvocationType="RequestResponse",
                           Payload=json.dumps({"action": "bootstrap", "credentials": credentials,
                                               "passwords": passwords}).encode())
    body = json.loads(result["Payload"].read())
    if result.get("FunctionError") or body.get("status") != "migrated":
        raise SystemExit("Password bootstrap failed; inspect migration logs. No credentials printed.")
    print("Password roles and schema configured. Run Deploy staging to inject credentials and verify.")


if __name__ == "__main__":
    main()
