import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, call, patch

spec = importlib.util.spec_from_file_location("backend_control", Path(__file__).parents[1] / "backend_control.py")
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)


class BackendControls(unittest.TestCase):
    def setUp(self):
        # The Deploy staging job runs these tests with the repository variable EMBED_FUNCTION in its environment once the
        # worker exists. Start every test without it; the tests that need the worker set it themselves.
        environment = patch.dict(control.os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        control.os.environ.pop("EMBED_FUNCTION", None)
        control.os.environ.pop("DISCOVERY_FUNCTION", None)

    def test_pause_and_resume_use_only_the_configured_api_and_bounded_values(self):
        for mode, concurrency in [("pause", 0), ("resume", 10)]:
            with self.subTest(mode=mode):
                client = Mock()
                client.get_function.return_value = {"Concurrency": {"ReservedConcurrentExecutions": concurrency}}
                with patch.dict(control.os.environ, {"API_FUNCTION": "staging-api"}), patch.object(control.boto3, "client", return_value=client), patch("builtins.print"):
                    control.set_mode(mode)
                client.put_function_concurrency.assert_called_once_with(FunctionName="staging-api", ReservedConcurrentExecutions=concurrency)
                client.delete_function_concurrency.assert_not_called()

    def test_the_embedding_worker_pauses_and_resumes_with_the_api_when_it_exists(self):
        for mode, api, embed in [("pause", 0, 0), ("resume", 10, 2)]:
            with self.subTest(mode=mode):
                client = Mock()
                reserved = {"staging-api": api, "staging-embed": embed}
                client.get_function.side_effect = lambda FunctionName: {"Concurrency": {"ReservedConcurrentExecutions": reserved[FunctionName]}}
                with patch.dict(control.os.environ, {"API_FUNCTION": "staging-api", "EMBED_FUNCTION": "staging-embed"}), \
                        patch.object(control.boto3, "client", return_value=client), patch("builtins.print"):
                    control.set_mode(mode)
                self.assertEqual(client.put_function_concurrency.call_args_list, [
                    call(FunctionName="staging-api", ReservedConcurrentExecutions=api),
                    call(FunctionName="staging-embed", ReservedConcurrentExecutions=embed)])

    def test_the_job_pull_pauses_and_resumes_with_the_api_so_a_schedule_cannot_wake_aurora(self):
        for mode, api, embed, discovery in [("pause", 0, 0, 0), ("resume", 10, 2, 1)]:
            with self.subTest(mode=mode):
                client = Mock()
                reserved = {"staging-api": api, "staging-embed": embed, "staging-discovery": discovery}
                client.get_function.side_effect = lambda FunctionName: {"Concurrency": {"ReservedConcurrentExecutions": reserved[FunctionName]}}
                with patch.dict(control.os.environ, {"API_FUNCTION": "staging-api", "EMBED_FUNCTION": "staging-embed",
                                                     "DISCOVERY_FUNCTION": "staging-discovery"}), \
                        patch.object(control.boto3, "client", return_value=client), patch("builtins.print"):
                    control.set_mode(mode)
                self.assertEqual(client.put_function_concurrency.call_args_list, [
                    call(FunctionName="staging-api", ReservedConcurrentExecutions=api),
                    call(FunctionName="staging-embed", ReservedConcurrentExecutions=embed),
                    call(FunctionName="staging-discovery", ReservedConcurrentExecutions=discovery)])

    def test_the_embedding_worker_is_left_alone_when_it_is_not_configured(self):
        client = Mock()
        client.get_function.return_value = {"Concurrency": {"ReservedConcurrentExecutions": 0}}
        with patch.dict(control.os.environ, {"API_FUNCTION": "staging-api"}), patch.object(control.boto3, "client", return_value=client), patch("builtins.print"):
            control.os.environ.pop("EMBED_FUNCTION", None)
            control.set_mode("pause")
        client.put_function_concurrency.assert_called_once_with(FunctionName="staging-api", ReservedConcurrentExecutions=0)

    def test_failed_embed_verification_names_the_worker(self):
        client = Mock()
        client.get_function.side_effect = [{"Concurrency": {"ReservedConcurrentExecutions": 0}}, {"Concurrency": {"ReservedConcurrentExecutions": 2}}]
        with patch.dict(control.os.environ, {"API_FUNCTION": "staging-api", "EMBED_FUNCTION": "staging-embed"}), patch.object(control.boto3, "client", return_value=client), patch("builtins.print"):
            with self.assertRaisesRegex(RuntimeError, "Embedding worker"):
                control.set_mode("pause")

    def test_failed_verification_is_reported(self):
        client = Mock()
        client.get_function.return_value = {"Concurrency": {"ReservedConcurrentExecutions": 10}}
        with patch.dict(control.os.environ, {"API_FUNCTION": "staging-api"}), patch.object(control.boto3, "client", return_value=client):
            with self.assertRaisesRegex(RuntimeError, "verification failed"):
                control.set_mode("pause")

    def test_unknown_mode_is_rejected_before_any_aws_call(self):
        with patch.object(control.boto3, "client") as client:
            with self.assertRaises(KeyError):
                control.set_mode("unlimited")
        client.assert_not_called()
