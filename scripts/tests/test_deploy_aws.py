import importlib.util
from io import BytesIO
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location("deploy_aws", Path(__file__).parents[1] / "deploy_aws.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
OLD = "repo@sha256:" + "a" * 64
NEW = "repo@sha256:" + "b" * 64


def function(image, revision):
    return {"Code": {"ResolvedImageUri": image}, "Configuration": {"RevisionId": revision}}


class ReleaseRecovery(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.invoke.return_value = {"Payload": BytesIO(b'{"status":"migrated"}')}
        self.client.get_function.side_effect = [function(OLD, "before"), function(OLD, "configured"), function(NEW, "after")]
        self.passwords = patch.object(release, "configure_password")
        self.passwords.start()
        self.addCleanup(self.passwords.stop)
        self.env = patch.dict(release.os.environ, {"MIGRATION_FUNCTION": "migrate", "API_FUNCTION": "api"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.sdk = patch.object(release.boto3, "client", return_value=self.client)
        self.factory = self.sdk.start()
        self.addCleanup(self.sdk.stop)

    def test_success_does_not_roll_back(self):
        with patch.object(release, "verify_api") as health:
            release.backend(NEW)
        health.assert_called_once()
        self.assertEqual(self.client.update_function_code.call_count, 2)
        config = self.factory.call_args.kwargs["config"]
        self.assertEqual(config.read_timeout, 330)
        self.assertEqual(config.retries["total_max_attempts"], 1)

    def test_failed_health_restores_old_digest_and_still_fails_release(self):
        with patch.object(release, "verify_api", side_effect=[RuntimeError("bad health"), None]) as health:
            with self.assertRaisesRegex(RuntimeError, "previous image restored and verified"):
                release.backend(NEW)
        self.client.update_function_code.assert_called_with(FunctionName="api", ImageUri=OLD, RevisionId="after")
        self.assertEqual(health.call_count, 2)
        self.assertEqual(self.client.invoke.call_count, 1)

    def test_failed_migration_never_changes_api(self):
        self.client.invoke.return_value = {"FunctionError": "Unhandled", "Payload": BytesIO(b'{}')}
        with self.assertRaisesRegex(RuntimeError, "Database migration failed"):
            release.backend(NEW)
        self.client.update_function_code.assert_called_once_with(FunctionName="migrate", ImageUri=NEW)

    def test_concurrent_operator_update_is_preserved(self):
        self.client.get_function.side_effect = [function(OLD, "before"), function(OLD, "configured"), function("operator-image", "operator")]
        with patch.object(release, "verify_api", side_effect=RuntimeError("bad health")):
            with self.assertRaisesRegex(RuntimeError, "changed concurrently"):
                release.backend(NEW)
        self.assertEqual(self.client.update_function_code.call_count, 2)

    def test_failed_rollback_is_reported(self):
        self.client.update_function_code.side_effect = [None, None, RuntimeError("rollback unavailable")]
        with patch.object(release, "verify_api", side_effect=RuntimeError("bad health")):
            with self.assertRaisesRegex(RuntimeError, "recovery needs attention: rollback unavailable"):
                release.backend(NEW)

    def test_manual_pause_blocks_migrations_and_release(self):
        current = function(OLD, "before")
        current["Concurrency"] = {"ReservedConcurrentExecutions": 0}
        self.client.get_function.side_effect = [current]
        with self.assertRaisesRegex(RuntimeError, "manually paused"):
            release.backend(NEW)
        self.client.invoke.assert_not_called()
        self.client.update_function_code.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class CredentialInjection(unittest.TestCase):
    def test_preserves_environment_and_uses_revision_guard(self):
        client = Mock()
        client.get_function_configuration.return_value = {
            "RevisionId": "configuration-before",
            "Environment": {"Variables": {"DOCUMENT_BUCKET": "documents", "DATABASE_AUTH": "iam"}}}
        store = Mock()
        store.get_secret_value.return_value = {"SecretString": '{"jobhunter_app":"' + 'x' * 64 + '"}'}
        with patch.dict(release.os.environ, {"DATABASE_CREDENTIALS_SECRET_ARN": "credential-secret"}), \
                patch.object(release.boto3, "client", return_value=store):
            release.configure_password(client, "api", "jobhunter_app")
        args = client.update_function_configuration.call_args.kwargs
        self.assertEqual(args["RevisionId"], "configuration-before")
        self.assertEqual(args["Environment"]["Variables"]["DOCUMENT_BUCKET"], "documents")
        self.assertEqual(args["Environment"]["Variables"]["DATABASE_USERNAME"], "jobhunter_app")
        self.assertEqual(args["Environment"]["Variables"]["DATABASE_PASSWORD"], "x" * 64)
