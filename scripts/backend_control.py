"""Manual API pause/resume; no database access or alarm-triggered actions."""
import argparse
import os

import boto3


def set_mode(mode):
    # Resume restores a bounded reservation, never unlimited concurrency.
    concurrency = {"pause": 0, "resume": 10}[mode]
    function = os.environ["API_FUNCTION"]
    client = boto3.client("lambda")
    client.put_function_concurrency(FunctionName=function, ReservedConcurrentExecutions=concurrency)
    actual = client.get_function(FunctionName=function).get("Concurrency", {}).get("ReservedConcurrentExecutions")
    if actual != concurrency:
        raise RuntimeError("Concurrency verification failed; inspect the API function before continuing.")
    print(f"Staging API {'paused' if mode == 'pause' else 'resumed'}; reserved concurrency = {actual}.")
    if mode == "pause":
        print("New API requests are disabled. In-flight work and administrator sessions must finish before Aurora can auto-pause.")
    else:
        print("The next signed-in request can resume Aurora. Re-run the deployment workflow if a release was blocked while paused.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["pause", "resume"])
    set_mode(parser.parse_args().mode)
