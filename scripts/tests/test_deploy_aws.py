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


class LlmWorkerRelease(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.get_function.return_value = function(OLD, "r1")
        self.client.get_function_configuration.return_value = {"RevisionId": "r2", "Environment": {"Variables": {"LLM_MODEL": "gemma4:26b"}}}
        sdk = patch.object(release.boto3, "client", return_value=self.client)
        sdk.start()
        self.addCleanup(sdk.stop)

    def run_llm(self, env):
        with patch.dict(release.os.environ, env, clear=False):
            for name in ("LLM_FUNCTION", "LLM_API_KEY"):
                if name not in env:
                    release.os.environ.pop(name, None)
            with patch("builtins.print") as shown:
                release.llm(NEW)
        return shown

    def test_nothing_happens_before_the_worker_exists(self):
        self.run_llm({})
        self.client.update_function_code.assert_not_called()

    def test_the_image_and_key_are_set_and_other_settings_are_kept_and_the_key_is_never_printed(self):
        shown = self.run_llm({"LLM_FUNCTION": "staging-llm", "LLM_API_KEY": "clsk_secret_value"})
        self.client.update_function_code.assert_called_once_with(FunctionName="staging-llm", ImageUri=NEW, RevisionId="r1")
        self.client.update_function_configuration.assert_called_once_with(
            FunctionName="staging-llm", RevisionId="r2", Environment={"Variables": {"LLM_MODEL": "gemma4:26b", "LLM_API_KEY": "clsk_secret_value"}})
        self.assertNotIn("clsk_secret_value", " ".join(str(call) for call in shown.call_args_list))

    def test_without_the_secret_the_existing_key_is_left_alone(self):
        self.run_llm({"LLM_FUNCTION": "staging-llm"})
        self.client.update_function_code.assert_called_once()
        self.client.update_function_configuration.assert_not_called()


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


class EmbedWorkerRelease(unittest.TestCase):
    def test_is_skipped_until_the_function_is_configured(self):
        with patch.dict(release.os.environ, {}, clear=False), patch.object(release.boto3, "client") as factory, patch("builtins.print"):
            release.os.environ.pop("EMBED_FUNCTION", None)
            release.embed(NEW)
        factory.assert_not_called()

    def test_updates_code_with_its_own_credential_and_a_revision_guard(self):
        client = Mock()
        client.get_function.return_value = function(OLD, "embed-revision")
        with patch.dict(release.os.environ, {"EMBED_FUNCTION": "embed"}), patch.object(release.boto3, "client", return_value=client), \
                patch.object(release, "configure_password") as configure, patch("builtins.print"):
            release.embed(NEW)
        configure.assert_called_once_with(client, "embed", "jobhunter_embedder")   # never the application or migration password
        client.update_function_code.assert_called_once_with(FunctionName="embed", ImageUri=NEW, RevisionId="embed-revision")
        client.get_waiter.return_value.wait.assert_called_with(FunctionName="embed")

    def test_a_missing_credential_is_reported_clearly_before_anything_changes(self):
        client, store = Mock(), Mock()
        store.get_secret_value.return_value = {"SecretString": '{"jobhunter_app":"' + "x" * 64 + '"}'}
        with patch.dict(release.os.environ, {"DATABASE_CREDENTIALS_SECRET_ARN": "credential-secret"}), \
                patch.object(release.boto3, "client", return_value=store):
            with self.assertRaisesRegex(RuntimeError, "run the operator bootstrap"):
                release.configure_password(client, "embed", "jobhunter_embedder")
        client.update_function_configuration.assert_not_called()
