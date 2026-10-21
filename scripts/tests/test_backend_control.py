import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location("backend_control", Path(__file__).parents[1] / "backend_control.py")
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)


class BackendControls(unittest.TestCase):
    def test_pause_and_resume_use_only_the_configured_api_and_bounded_values(self):
        for mode, concurrency in [("pause", 0), ("resume", 10)]:
            with self.subTest(mode=mode):
                client = Mock()
                client.get_function.return_value = {"Concurrency": {"ReservedConcurrentExecutions": concurrency}}
                with patch.dict(control.os.environ, {"API_FUNCTION": "staging-api"}), patch.object(control.boto3, "client", return_value=client), patch("builtins.print"):
                    control.set_mode(mode)
                client.put_function_concurrency.assert_called_once_with(FunctionName="staging-api", ReservedConcurrentExecutions=concurrency)
                client.delete_function_concurrency.assert_not_called()

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
