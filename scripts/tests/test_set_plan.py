import importlib.util
from io import BytesIO, StringIO
import json
from pathlib import Path
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch
from uuid import NAMESPACE_URL, uuid5

from botocore.exceptions import ClientError

spec = importlib.util.spec_from_file_location("set_plan", Path(__file__).parents[1] / "set_plan.py")
plan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plan)

SUB_A = "11111111-1111-4111-8111-111111111111"
SUB_B = "22222222-2222-4222-8222-222222222222"


def user_not_found():
    return ClientError({"Error": {"Code": "UserNotFoundException", "Message": "User not found."}}, "AdminGetUser")


class UserIdRule(unittest.TestCase):
    def test_user_id_matches_the_backend_uuid5_rule(self):
        issuer = "https://cognito-idp.ap-southeast-1.amazonaws.com/ap-southeast-1_rqE5iKEpf"
        self.assertEqual(plan.user_id(issuer, SUB_A), uuid5(NAMESPACE_URL, f"{issuer}#{SUB_A}"))


class Resolve(unittest.TestCase):
    def test_resolve_maps_sub_to_user_id_and_lists_emails_not_in_cognito(self):
        cognito = Mock()
        cognito.admin_get_user.side_effect = [
            {"UserAttributes": [{"Name": "email", "Value": "a@example.com"}, {"Name": "sub", "Value": SUB_A}]},
            user_not_found(),
        ]
        resolved, missing = plan.resolve(cognito, "ap-southeast-1_rqE5iKEpf", ["a@example.com", "b@example.com"])
        issuer = f"https://cognito-idp.{plan.REGION}.amazonaws.com/ap-southeast-1_rqE5iKEpf"
        self.assertEqual(resolved, {"a@example.com": str(uuid5(NAMESPACE_URL, f"{issuer}#{SUB_A}"))})
        self.assertEqual(missing, ["b@example.com"])

    def test_resolve_propagates_unexpected_cognito_errors(self):
        cognito = Mock()
        cognito.admin_get_user.side_effect = ClientError(
            {"Error": {"Code": "InternalErrorException", "Message": "boom"}}, "AdminGetUser")
        with self.assertRaises(ClientError):
            plan.resolve(cognito, "ap-southeast-1_rqE5iKEpf", ["a@example.com"])


class Invoke(unittest.TestCase):
    def test_invoke_sends_the_exact_payload_and_returns_it(self):
        client = Mock()
        client.invoke.return_value = {"Payload": BytesIO(b'{"status":"ok","updated":1,"not_found":[]}')}
        ids = [str(uuid5(NAMESPACE_URL, f"issuer#{SUB_A}"))]
        result = plan.invoke(client, "migrate", "premium", ids)
        client.invoke.assert_called_once_with(FunctionName="migrate", InvocationType="RequestResponse",
                                              Payload=json.dumps({"action": "set_plan", "plan": "premium", "user_ids": ids}))
        self.assertEqual(result, {"status": "ok", "updated": 1, "not_found": []})

    def test_invoke_raises_when_the_lambda_reports_a_function_error(self):
        client = Mock()
        client.invoke.return_value = {"FunctionError": "Unhandled", "Payload": BytesIO(b"{}")}
        with self.assertRaisesRegex(RuntimeError, "migrate Lambda logs"):
            plan.invoke(client, "migrate", "free", [SUB_A])

    def test_invoke_raises_when_the_lambda_status_is_not_ok(self):
        client = Mock()
        client.invoke.return_value = {"Payload": BytesIO(b'{"status":"error"}')}
        with self.assertRaisesRegex(RuntimeError, "migrate Lambda logs"):
            plan.invoke(client, "migrate", "free", [SUB_A])


class Main(unittest.TestCase):
    def test_main_aborts_without_invoking_when_the_prompt_is_declined(self):
        cognito = Mock()
        cognito.admin_get_user.return_value = {"UserAttributes": [{"Name": "sub", "Value": SUB_A}]}
        lambda_client = Mock()
        factory = Mock(side_effect=lambda service, **kwargs: cognito if service == "cognito-idp" else lambda_client)
        with patch.object(plan.boto3, "client", factory), patch("builtins.input", return_value="n"), patch("builtins.print"):
            code = plan.main(["--plan", "premium", "a@example.com"])
        self.assertEqual(code, 1)
        lambda_client.invoke.assert_not_called()

    def test_main_yes_maps_not_found_back_to_the_email_and_exits_non_zero(self):
        cognito = Mock()
        cognito.admin_get_user.side_effect = [
            {"UserAttributes": [{"Name": "sub", "Value": SUB_A}]},
            {"UserAttributes": [{"Name": "sub", "Value": SUB_B}]},
        ]
        lambda_client = Mock()

        def invoke_side_effect(FunctionName, InvocationType, Payload):
            event = json.loads(Payload)
            return {"Payload": BytesIO(json.dumps(
                {"status": "ok", "updated": 1, "not_found": [event["user_ids"][1]]}).encode())}

        lambda_client.invoke.side_effect = invoke_side_effect
        factory = Mock(side_effect=lambda service, **kwargs: cognito if service == "cognito-idp" else lambda_client)
        output = StringIO()
        with patch.object(plan.boto3, "client", factory), redirect_stdout(output):
            code = plan.main(["--plan", "premium", "a@example.com", "b@example.com", "--yes"])
        self.assertEqual(code, 1)
        self.assertIn("b@example.com has not signed in yet", output.getvalue())
        self.assertIn("Updated 1 user(s) to premium.", output.getvalue())
        # The subject (a Cognito attribute the operator did not type) is never printed.
        self.assertNotIn(SUB_B, output.getvalue())


if __name__ == "__main__":
    unittest.main()
