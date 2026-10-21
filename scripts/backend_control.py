"""Manual API pause/resume; no database access or alarm-triggered actions."""
import argparse
import os

import boto3


def set_mode(mode):
    # Resume restores a bounded reservation, never unlimited concurrency. The embedding worker (when it exists) pauses
    # with the API, so paused really means nothing can wake Aurora.
    concurrency = {"pause": 0, "resume": 10}[mode]
    targets = [(os.environ["API_FUNCTION"], concurrency, "API")]
    if os.environ.get("EMBED_FUNCTION"):
        targets.append((os.environ["EMBED_FUNCTION"], {"pause": 0, "resume": 2}[mode], "Embedding worker"))
    client = boto3.client("lambda")
    for function, reserved, label in targets:
        client.put_function_concurrency(FunctionName=function, ReservedConcurrentExecutions=reserved)
        actual = client.get_function(FunctionName=function).get("Concurrency", {}).get("ReservedConcurrentExecutions")
        if actual != reserved:
            raise RuntimeError(f"Concurrency verification failed; inspect the {label} function before continuing.")
        print(f"Staging {label} {'paused' if mode == 'pause' else 'resumed'}; reserved concurrency = {actual}.")
    if mode == "pause":
        print("New API requests are disabled. In-flight work and administrator sessions must finish before Aurora can auto-pause.")
    else:
        print("The next signed-in request can resume Aurora. Re-run the deployment workflow if a release was blocked while paused.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["pause", "resume"])
    set_mode(parser.parse_args().mode)
