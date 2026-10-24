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


def llm(image: str):
    """Update the shared LLM worker (design brief 12) to the API image and give it the model key.

    The key is the GitHub Actions secret LLM_API_KEY, passed in the environment of this step (never argv, never printed).
    Skipped when LLM_FUNCTION is not configured, so a release before the worker exists is unchanged."""
    function = os.environ.get("LLM_FUNCTION")
    if not function:
        print("LLM_FUNCTION is not set; the LLM worker is not deployed.")
        return
    client = boto3.client("lambda", config=Config(read_timeout=120, connect_timeout=10, retries={"total_max_attempts": 1}))
    current = client.get_function(FunctionName=function)
    client.update_function_code(FunctionName=function, ImageUri=image, RevisionId=current["Configuration"]["RevisionId"])
    client.get_waiter("function_updated_v2").wait(FunctionName=function)
    key = os.environ.get("LLM_API_KEY", "")
    if key:
        current = client.get_function_configuration(FunctionName=function)
        variables = dict(current.get("Environment", {}).get("Variables", {}))
        variables["LLM_API_KEY"] = key
        client.update_function_configuration(FunctionName=function, RevisionId=current["RevisionId"], Environment={"Variables": variables})
        client.get_waiter("function_updated_v2").wait(FunctionName=function)
        print("LLM worker updated; model key set from the LLM_API_KEY secret")
    else:
        print("LLM worker updated; LLM_API_KEY secret is not set, so its model key is unchanged")


def pull_jobs(image: str):
    """Update the two job-pull Lambdas (design brief 04) to the API image.

    ``DISCOVERY_FUNCTION`` (outside the VPC, fetches the public job feeds) and ``IMPORT_FUNCTION`` (inside the VPC, writes
    Aurora) run the same image as the API; each is skipped when its variable is unset, so a release before they exist is
    unchanged. The import function also gets its own database password (the application role: the shared jobs table has no
    row-level security). Optional source keys (Adzuna) come from GitHub secrets in this step's environment, never argv,
    and are never printed. Like the other workers this runs after the API release: the migration has already run."""
    client = boto3.client("lambda", config=Config(read_timeout=120, connect_timeout=10, retries={"total_max_attempts": 1}))
    importer = os.environ.get("IMPORT_FUNCTION")
    discovery = os.environ.get("DISCOVERY_FUNCTION")
    if not importer and not discovery:
        print("DISCOVERY_FUNCTION and IMPORT_FUNCTION are not set; the job pull is not deployed.")
        return
    if importer:
        configure_password(client, importer, "jobhunter_app")
        _update_code(client, importer, image)
        print("Job import function updated")
    if discovery:
        _update_code(client, discovery, image)
        keys = {name: os.environ[name] for name in ("ADZUNA_APP_ID", "ADZUNA_APP_KEY") if os.environ.get(name)}
        if keys:
            current = client.get_function_configuration(FunctionName=discovery)
            variables = dict(current.get("Environment", {}).get("Variables", {}))
            variables.update(keys)
            client.update_function_configuration(FunctionName=discovery, RevisionId=current["RevisionId"],
                                                 Environment={"Variables": variables})
            client.get_waiter("function_updated_v2").wait(FunctionName=discovery)
        print("Job discovery function updated" + ("; source keys set from secrets" if keys else ""))


def _update_code(client, function, image):
    current = client.get_function(FunctionName=function)
    client.update_function_code(FunctionName=function, ImageUri=image, RevisionId=current["Configuration"]["RevisionId"])
    client.get_waiter("function_updated_v2").wait(FunctionName=function)


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
    parser.add_argument("--llm-image", help="immutable digest of the API image, reused for the LLM worker (design brief 12)")
    parser.add_argument("--pull-image", help="immutable digest of the API image, reused for the job-pull functions (design brief 04)")
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
    if args.llm_image:
        if "@sha256:" not in args.llm_image:
            parser.error("Use an immutable image digest")
        llm(args.llm_image)
    if args.pull_image:
        if "@sha256:" not in args.pull_image:
            parser.error("Use an immutable image digest")
        pull_jobs(args.pull_image)
    if args.web:
        frontend(args.web)
