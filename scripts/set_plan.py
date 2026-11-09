"""Operator-only: set staging users' plan (free/premium) by email through the migrate Lambda; no API route."""
import argparse
import json
import os
from uuid import NAMESPACE_URL, uuid5

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

REGION = "ap-southeast-1"
USER_POOL_ID = os.environ.get("USER_POOL_ID", "ap-southeast-1_rqE5iKEpf")
MIGRATION_FUNCTION = os.environ.get("MIGRATION_FUNCTION", "jobhunter-staging-migrate")


def user_id(issuer, sub):
    # Same rule as backend/src/job_hunter/adapters/auth.py, which derives each tenant id as
    # uuid5(NAMESPACE_URL, f"{cognito_issuer}#{subject}"). cognito_issuer is
    # "https://cognito-idp.{region}.amazonaws.com/{user_pool_id}" (no trailing slash; infra/aws/main.tf).
    return uuid5(NAMESPACE_URL, f"{issuer}#{sub}")


def resolve(cognito, pool_id, emails):
    # Build the issuer exactly the way infra/aws/main.tf does (https://<pool endpoint>).
    issuer = f"https://cognito-idp.{REGION}.amazonaws.com/{pool_id}"
    resolved, missing = {}, []
    for email in emails:
        try:
            user = cognito.admin_get_user(UserPoolId=pool_id, Username=email)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") == "UserNotFoundException":
                missing.append(email)
                continue
            raise
        sub = next(attr["Value"] for attr in user["UserAttributes"] if attr["Name"] == "sub")
        resolved[email] = str(user_id(issuer, sub))
    return resolved, missing


def invoke(client, function, plan, ids):
    event = {"action": "set_plan", "plan": plan, "user_ids": ids}
    result = client.invoke(FunctionName=function, InvocationType="RequestResponse", Payload=json.dumps(event))
    payload = json.loads(result["Payload"].read())
    if result.get("FunctionError") or payload.get("status") != "ok":
        raise RuntimeError("set_plan failed; inspect the migrate Lambda logs")
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True, choices=["free", "premium"])
    parser.add_argument("emails", nargs="+", metavar="email")
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = parser.parse_args(argv)
    if len(args.emails) > 20:
        parser.error("at most 20 emails can be set at once")
    cognito = boto3.client("cognito-idp", region_name=REGION)
    resolved, not_in_cognito = resolve(cognito, USER_POOL_ID, args.emails)
    for email in args.emails:
        print(f"{email}: {resolved[email]}" if email in resolved else f"{email}: not in Cognito")
    if not_in_cognito:
        print("Not in Cognito:", ", ".join(not_in_cognito))
    if not resolved:
        return 1
    if not args.yes:
        answer = input(f"Set plan to {args.plan} for {len(resolved)} user(s) on staging? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            return 1
    # A paused Aurora can take minutes to resume (the Lambda retries for ~3). No invoke retries,
    # as in scripts/deploy_aws.py, so a client timeout never sends the request twice.
    client = boto3.client("lambda", region_name=REGION, config=Config(read_timeout=330, retries={"max_attempts": 0}))
    result = invoke(client, MIGRATION_FUNCTION, args.plan, list(resolved.values()))
    print(f"Updated {result['updated']} user(s) to {args.plan}.")
    by_id = {uid: email for email, uid in resolved.items()}
    for uid in result.get("not_found", []):
        print(f"{by_id.get(uid, uid)} has not signed in yet (no users row) — ask them to sign in once, then re-run")
    return 0 if not not_in_cognito and not result.get("not_found") else 1


if __name__ == "__main__":
    raise SystemExit(main())
