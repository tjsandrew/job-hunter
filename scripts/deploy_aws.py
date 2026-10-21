"""Deploy a tested frontend archive and (optionally) an immutable backend image."""
import argparse
import json
import os
from pathlib import Path
import time
from urllib.request import Request, urlopen
import zipfile

import boto3
from botocore.config import Config


def configure_password(client, function, role):
    # Retrieve outside the VPC. Never print credentials or include them in argv.
    secret = os.environ["DATABASE_CREDENTIALS_SECRET_ARN"]
    passwords = json.loads(boto3.client("secretsmanager").get_secret_value(SecretId=secret)["SecretString"])
    if role not in passwords:
        raise RuntimeError(f"No stored database credential for {role}; run the operator bootstrap first (see docs/deployment).")
    password = passwords[role]
    if not isinstance(password, str) or len(password) < 32:
        raise ValueError("Invalid stored database credential")
    current = client.get_function_configuration(FunctionName=function)
    variables = dict(current.get("Environment", {}).get("Variables", {}))
    variables.update(DATABASE_AUTH="password", DATABASE_USERNAME=role, DATABASE_PASSWORD=password)
    client.update_function_configuration(FunctionName=function, RevisionId=current["RevisionId"],
                                         Environment={"Variables": variables})
    client.get_waiter("function_updated_v2").wait(FunctionName=function)


def backend(image: str):
    # A synchronous migration can take 300s. Disable invoke retries so a client
    # read timeout cannot silently execute the migration function twice.
    client = boto3.client("lambda", config=Config(read_timeout=330, connect_timeout=10,
                                                 retries={"total_max_attempts": 1}))
    migration = os.environ["MIGRATION_FUNCTION"]
    api = os.environ["API_FUNCTION"]
    previous = client.get_function(FunctionName=api)
    if previous.get("Concurrency", {}).get("ReservedConcurrentExecutions") == 0:
        raise RuntimeError("Staging is manually paused. Use Pause or resume staging backend before releasing.")
    previous_image = previous["Code"]["ResolvedImageUri"]
    if "@sha256:" not in previous_image:
        raise RuntimeError("Cannot deploy without an immutable rollback image")
    # Migrate with the new code before switching traffic. Migrations must remain
    # compatible with the currently running API; destructive changes are manual.
    client.update_function_code(FunctionName=migration, ImageUri=image)
    client.get_waiter("function_updated_v2").wait(FunctionName=migration)
    configure_password(client, migration, "jobhunter_migrator")
    result = client.invoke(FunctionName=migration, InvocationType="RequestResponse", Payload=b"{}")
    payload = json.loads(result["Payload"].read())
    if result.get("FunctionError") or payload.get("status") != "migrated":
        raise RuntimeError("Database migration failed; inspect migration Lambda logs")
    try:
        configure_password(client, api, "jobhunter_app")
        current_api = client.get_function(FunctionName=api)
        client.update_function_code(FunctionName=api, ImageUri=image,
                                    RevisionId=current_api["Configuration"]["RevisionId"])
        client.get_waiter("function_updated_v2").wait(FunctionName=api)
        verify_api()
    except Exception as release_error:
        # Restore code only, never reverse a database migration. Guard against
        # overwriting a concurrent operator update using both digest and revision.
        try:
            current = client.get_function(FunctionName=api)
            current_image = current["Code"]["ResolvedImageUri"]
            if current_image != previous_image:
                if current_image != image:
                    raise RuntimeError("API changed concurrently; refusing to overwrite it")
                client.update_function_code(FunctionName=api, ImageUri=previous_image,
                                            RevisionId=current["Configuration"]["RevisionId"])
                client.get_waiter("function_updated_v2").wait(FunctionName=api)
            verify_api()
        except Exception as rollback_error:
            raise RuntimeError(f"API release failed; automatic recovery needs attention: {rollback_error}") from release_error
        raise RuntimeError("API release failed; previous image restored and verified. Database migrations remain applied.") from release_error


def embed(image: str):
    """Update the embedding worker (design brief 11) to an immutable image and give it its own database password.

    Skipped when EMBED_FUNCTION is not configured, so a release before the worker exists is unchanged. It runs after the
    API release: the worker's database role and grants come from the migration function, which has already run."""
    function = os.environ.get("EMBED_FUNCTION")
    if not function:
        print("EMBED_FUNCTION is not set; the embedding worker is not deployed yet.")
        return
    client = boto3.client("lambda", config=Config(read_timeout=120, connect_timeout=10, retries={"total_max_attempts": 1}))
    configure_password(client, function, "jobhunter_embedder")
    current = client.get_function(FunctionName=function)
    client.update_function_code(FunctionName=function, ImageUri=image, RevisionId=current["Configuration"]["RevisionId"])
    client.get_waiter("function_updated_v2").wait(FunctionName=function)
    print("Embedding worker updated")


def verify_api():
    base = os.environ["VITE_API_BASE_URL"].rstrip("/")
    with urlopen(base + "/health", timeout=30) as response:
        if json.load(response).get("status") != "ok":
            raise RuntimeError("API health check failed")
    from urllib.error import HTTPError
    try:
        urlopen(base + "/me", timeout=30)
    except HTTPError as exc:
        if exc.code not in (401, 403):
            raise
    else:
        raise RuntimeError("Personal API unexpectedly allowed anonymous access")


def frontend(directory: Path):
    archive = directory.parent / "web-deployment.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
        for file in sorted(directory.rglob("*")):
            if file.is_file():
                output.write(file, file.relative_to(directory))
    client = boto3.client("amplify")
    args = {"appId": os.environ["AMPLIFY_APP_ID"], "branchName": "main"}
    deployment = client.create_deployment(**args)
    with urlopen(Request(deployment["zipUploadUrl"], data=archive.read_bytes(), method="PUT"), timeout=120):
        pass
    client.start_deployment(**args, jobId=deployment["jobId"])
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        job = client.get_job(**args, jobId=deployment["jobId"])["job"]["summary"]
        if job["status"] == "SUCCEED":
            print("Website deployment succeeded")
            return
        if job["status"] in {"FAILED", "CANCELLED"}:
            raise RuntimeError("Amplify deployment failed; inspect the Amplify job")
        time.sleep(5)
    raise TimeoutError("Amplify job did not finish in 10 minutes")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--image")
    parser.add_argument("--embed-image", help="immutable digest of the embedding worker image (design brief 11)")
    parser.add_argument("--web", type=Path)
    args = parser.parse_args()
    if args.image:
        if "@sha256:" not in args.image:
            parser.error("Use an immutable image digest")
        backend(args.image)
    if args.embed_image:
        if "@sha256:" not in args.embed_image:
            parser.error("Use an immutable image digest")
        embed(args.embed_image)
    if args.web:
        frontend(args.web)
