import importlib.util
from io import BytesIO
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location("pull_jobs", Path(__file__).parents[1] / "pull_jobs.py")
pull_jobs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pull_jobs)

RESULT = {"fetched": 40, "max_new": 10, "failures": [{"source": "lever", "board": "x", "error": "timeout"}], "truncated_boards": [],
          "import": {"new": 10, "updated": 1, "unchanged": 20, "deferred": 9, "errors": 0, "embed_flag_written": True}}


def reply(body, error=None):
    response = {"Payload": BytesIO(json.dumps(body).encode())}
    if error:
        response["FunctionError"] = error
    return response


class PullJobs(unittest.TestCase):
    def test_the_batch_size_is_sent_and_the_answer_is_returned(self):
        client = Mock()
        client.invoke.return_value = reply(RESULT)
        self.assertEqual(pull_jobs.pull(client, "discovery", 7), RESULT)
        call = client.invoke.call_args.kwargs
        self.assertEqual(call["FunctionName"], "discovery")
        self.assertEqual(call["InvocationType"], "RequestResponse")
        self.assertEqual(json.loads(call["Payload"]), {"max_new": 7})

    def test_a_function_error_fails_the_run_with_the_message(self):
        client = Mock()
        client.invoke.return_value = reply({"errorMessage": "import step failed"}, error="Unhandled")
        with self.assertRaisesRegex(RuntimeError, "import step failed"):
            pull_jobs.pull(client, "discovery", 10)

    def test_the_summary_reports_counts_and_source_problems(self):
        text = pull_jobs.summary(RESULT)
        self.assertIn("New jobs added: **10**", text)
        self.assertIn("Left for the next pull: 9", text)
        self.assertIn("Source problem", text)
        self.assertIn("embedding worker", text)

    def test_the_summary_says_when_nothing_was_loaded(self):
        text = pull_jobs.summary({"fetched": 0, "failures": [], "import": None})
        self.assertIn("Nothing was loaded", text)

    def test_a_paused_staging_is_detected(self):
        client = Mock()
        client.get_function.return_value = {"Concurrency": {"ReservedConcurrentExecutions": 0}}
        self.assertTrue(pull_jobs.paused(client, "api"))
        client.get_function.return_value = {"Concurrency": {"ReservedConcurrentExecutions": 10}}
        self.assertFalse(pull_jobs.paused(client, "api"))
        self.assertFalse(pull_jobs.paused(client, ""))

    def test_main_needs_the_function_name_and_refuses_while_paused(self):
        with patch.dict(pull_jobs.os.environ, {}, clear=False):
            pull_jobs.os.environ.pop("DISCOVERY_FUNCTION", None)
            with patch("sys.stderr"):
                self.assertEqual(pull_jobs.main(), 1)
        client = Mock()
        client.get_function.return_value = {"Concurrency": {"ReservedConcurrentExecutions": 0}}
        env = {"DISCOVERY_FUNCTION": "discovery", "API_FUNCTION": "api", "MAX_NEW": "10"}
        with patch.dict(pull_jobs.os.environ, env), patch.object(pull_jobs.boto3, "client", return_value=client), patch("sys.stderr"):
            self.assertEqual(pull_jobs.main(), 1)
        client.invoke.assert_not_called()


if __name__ == "__main__":
    unittest.main()
